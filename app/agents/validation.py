"""Validation / Guardrail node: runs on the DRAFT answer before the user sees it as final."""
from langchain_core.messages import AIMessage

from app.agents.runtime import agent_node
from app.context import emit
from app.security import brand_violations, check_citations, redact_sensitive

FALLBACK = "I can't provide that response. Please rephrase your question or contact the knowledge-management team."


def _sources(chunks: list[dict], cited: set[str]) -> list[dict]:
    seen, out = set(), []
    for c in chunks:
        if c["chunk_id"] in cited and c["chunk_id"] not in seen:
            seen.add(c["chunk_id"])
            out.append({k: c.get(k) for k in ("chunk_id", "doc_id", "title", "department", "document_type", "access_level", "created_date", "score", "dense_score", "sparse_score")}
                       | {"snippet": c["text"].strip()[:280]})
    return out


@agent_node("validation", "Validating answer (citations, secrets, brand)", fallback={"final": FALLBACK, "validation": {"ok": False}})
async def validation(state: dict) -> dict:
    draft = (state.get("draft") or "").strip()
    chunks = state.get("chunks", [])
    needs_citations = state.get("plan", {}).get("route") != "direct" and bool(chunks)

    answer, invalid, valid = check_citations(draft, {c["chunk_id"] for c in chunks})
    answer, redactions = redact_sensitive(answer)
    brand = brand_violations(answer)

    problems = []
    if len(answer) < 3:
        problems.append("empty_response")
    if invalid:
        problems.append(f"hallucinated_citations_removed:{len(invalid)}")
    if redactions:
        problems.append(f"redacted_sensitive:{redactions}")
    if brand:
        problems.append("brand_violation")
    if needs_citations and not valid:
        problems.append("no_valid_citations")

    blocking = "empty_response" in problems or "brand_violation" in problems
    if blocking:
        answer = FALLBACK
    elif "no_valid_citations" in problems:
        answer += "\n\n_Note: this answer could not be linked to specific source passages; please verify before relying on it._"

    result = {"ok": not blocking, "problems": problems, "valid_citations": valid, "invalid_citations": invalid}
    await emit("validation", stage="output", **result)
    sources = _sources(chunks, set(valid))
    await emit("final", answer=answer, sources=sources, validation=result, errors=state.get("errors", []))
    return {"final": answer, "sources": sources, "validation": result, "messages": [AIMessage(content=answer)]}
