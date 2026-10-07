"""Response Agent: grounded answer generation with streamed tokens."""
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents import prompts
from app.agents.runtime import agent_node
from app.config import settings
from app.context import emit
from app.errors import LLMUnavailable
from app.llm import llm_stream
from app.security import sanitize_untrusted

MAX_EVIDENCE_CHUNKS = 10


def build_evidence(chunks: list[dict]) -> str:
    blocks = []
    for c in chunks[:MAX_EVIDENCE_CHUNKS]:
        clean, _ = sanitize_untrusted(c["text"])  # indirect-injection defence on retrieved content
        blocks.append(f"<document id=\"{c['chunk_id']}\" title=\"{c['title']}\" type=\"{c['document_type']}\" date=\"{c['created_date']}\">\n{clean}\n</document>")
    return "\n".join(blocks) or "(no documents retrieved)"


def build_tool_context(tool_results: list[dict]) -> str:
    out = []
    for r in tool_results:
        body = json.dumps(r["output"], default=str)[:3000] if r["status"] == "ok" else f"{r['status']}: {r['error']}"
        out.append(f"<tool_result name=\"{r['tool']}\">{body}</tool_result>")
    return "\n".join(out) or "(no tools used)"


def extractive_fallback(chunks: list[dict], reason: str) -> str:
    """No LLM available: return the best evidence verbatim with citations rather than failing."""
    if not chunks:
        return f"I'm unable to generate an answer right now ({reason}) and found no matching documents. Please try again shortly."
    lines = [f"The language model is temporarily unavailable, so here are the most relevant passages ({reason}):"]
    for c in chunks[:3]:
        lines.append(f"- **{c['title']}** [{c['chunk_id']}]: {c['text'].strip().splitlines()[0][:220]}")
    return "\n".join(lines)


@agent_node("response", "Generating final response", fallback={"draft": "I'm sorry - I couldn't complete that request. Please try again."})
async def response_agent(state: dict) -> dict:
    plan = state.get("plan", {})
    chunks = state.get("chunks", [])
    research = state.get("research") or {}
    errors = list(state.get("errors", []))

    context = f"EVIDENCE:\n{build_evidence(chunks)}\n\nTOOL RESULTS:\n{build_tool_context(state.get('tool_results', []))}"
    if research.get("findings"):
        context += f"\n\nRESEARCH FINDINGS (aggregated by sub-agents; stats={research.get('stats')}):\n{json.dumps(research['findings'])[:6000]}"
    if errors:
        context += f"\n\nSYSTEM NOTES (limitations to mention if relevant): {'; '.join(errors)}"

    history = [m for m in state.get("messages", [])[:-1]][-settings.memory_window:]
    messages = [SystemMessage(content=prompts.RESPONSE.format(bank=prompts.BANK)), *history,
                HumanMessage(content=f"{context}\n\nUSER QUESTION: {plan.get('rewritten_query') or state['question']}")]

    draft = ""
    try:
        async for token in llm_stream(messages):
            draft += token
            await emit("token", text=token)
    except LLMUnavailable as exc:
        await emit("degraded", node="response", message="LLM unavailable - returning extractive answer")
        errors.append("response LLM unavailable")
        draft = extractive_fallback(chunks, "LLM unavailable")
        await emit("token", text=draft)
        _ = exc
    return {"draft": draft, "errors": errors}
