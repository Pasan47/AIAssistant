"""Supervisor: intent understanding, task decomposition, routing."""
import logging
import re
from datetime import date

from langchain_core.messages import AIMessage, HumanMessage

from app.agents import prompts
from app.agents.runtime import agent_node
from app.config import settings
from app.context import current_user, emit
from app.errors import LLMUnavailable
from app.llm import llm_json
from app.schemas import Plan, SearchFilters, ToolRequest
from app.services import get_registry

log = logging.getLogger(__name__)
_BROAD = re.compile(r"\b(all|every|recurring|trend|across|over the (last|past)|summari[sz]e (all|the))\b", re.I)
_LOOKUP = re.compile(r"\b(who owns|owner|on[- ]call|who is|employee|service catalog|which team)\b", re.I)


def format_history(messages: list, limit: int) -> str:
    lines = []
    for m in messages[-limit:]:
        who = "User" if isinstance(m, HumanMessage) else "Assistant" if isinstance(m, AIMessage) else "Other"
        lines.append(f"{who}: {str(m.content)[:600]}")
    return "\n".join(lines) or "(no prior turns)"


def heuristic_plan(question: str) -> Plan:
    """Used when the LLM is down: keyword routing keeps the assistant useful (graceful degradation)."""
    if _BROAD.search(question):
        return Plan(intent="deep_research", route="research", rewritten_query=question, reasoning="heuristic: broad question")
    tools = [ToolRequest(name="employee_lookup", args={"query": question[:60]})] if _LOOKUP.search(question) else []
    return Plan(intent="knowledge_qa", route="retrieval", rewritten_query=question, tools=tools, reasoning="heuristic routing (LLM unavailable)")


@agent_node("supervisor", "Understanding intent and routing")
async def supervisor(state: dict) -> dict:
    user = current_user.get()
    question = state["question"]
    system = prompts.SUPERVISOR.format(bank=prompts.BANK, today=date.today().isoformat()).format(
        role=user.role.value, tools=get_registry().describe_for(user.role))
    history = format_history(state.get("messages", [])[:-1], settings.memory_window)  # last message is the current question
    try:
        plan = await llm_json(system, f"Conversation so far:\n{history}\n\nLatest user message:\n{question}", Plan)
    except LLMUnavailable:
        plan = heuristic_plan(question)
        await emit("degraded", node="supervisor", message="LLM unavailable - using heuristic routing")

    plan.tools = [t for t in plan.tools if t.name != "knowledge_search"][:3]
    plan.filters = plan.filters or SearchFilters()
    await emit("plan", intent=plan.intent, route=plan.route, rewritten_query=plan.rewritten_query,
               filters=plan.filters.model_dump(exclude_none=True), tools=[t.name for t in plan.tools],
               sub_tasks=plan.sub_tasks, reasoning=plan.reasoning)
    return {"plan": plan.model_dump()}
