"""Research Agent = the Recursive Language Model (RLM) loop, kept separate from normal queries.

 1 explore    : LLM writes a Python search plan (sandboxed AST allow-list) instead of reading whole documents
 2 filter     : plan searches are filtered by type/date and by the user's ACL (enforced in the retriever)
 3 decompose  : retrieved documents are split into small batches
 4 sub-agents : each batch is analysed independently and concurrently (failure-isolated)
 5 aggregate  : partial findings are tree-reduced recursively into one result
 6 analyse    : python_analysis computes recurrence counts over the examined documents (if role allows)
"""
import asyncio
import logging
from datetime import date

from app.agents import prompts
from app.agents.runtime import agent_node
from app.config import settings
from app.context import current_user, emit
from app.errors import LLMUnavailable, RetrievalUnavailable
from app.llm import llm_json
from app.rlm.map_reduce import group_by_document, map_reduce
from app.rlm.sandbox import PlanRejected, run_plan
from app.schemas import Plan
from app.services import get_registry, get_retriever
from pydantic import BaseModel

log = logging.getLogger(__name__)


class _PlanCode(BaseModel):
    code: str


def _default_plan(query: str, plan: Plan) -> str:
    f = plan.filters.model_dump(exclude_none=True)
    kwargs = "".join(f", {k}={v!r}" for k, v in f.items())
    return f"results = []\nresults += search({query!r}{kwargs}, top_k=15)\nresult = results"


async def _make_plan_code(plan: Plan) -> str:
    try:
        ask = f"Investigation: {plan.rewritten_query}\nSuggested filters: {plan.filters.model_dump(exclude_none=True)}"
        return (await llm_json(prompts.RESEARCH_PLAN.format(today=date.today().isoformat()), ask, _PlanCode)).code
    except LLMUnavailable:
        await emit("degraded", node="research", message="LLM unavailable - using default search plan")
        return _default_plan(plan.rewritten_query, plan)


async def _execute_plan(code: str, plan: Plan, user) -> list[dict]:
    loop, retriever = asyncio.get_running_loop(), get_retriever()

    def search(query, document_type=None, department=None, date_from=None, date_to=None, top_k=10):
        # called from the sandbox thread -> hop back onto the event loop; ACL enforced inside the retriever
        coro = retriever.search(user, str(query), department, document_type, date_from, date_to, min(int(top_k), 15))
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=30)["chunks"]

    return await asyncio.wait_for(
        asyncio.to_thread(run_plan, code, search, settings.rlm_max_search_calls), settings.rlm_plan_timeout_s
    )


@agent_node("research", "Deep research (RLM): plan -> batch -> sub-agents -> aggregate",
            fallback={"chunks": [], "research": {}})
async def research_agent(state: dict) -> dict:
    user, registry = current_user.get(), get_registry()
    plan = Plan.model_validate(state["plan"])
    errors = list(state.get("errors", []))

    # 1. python search plan
    code = await _make_plan_code(plan)
    await emit("rlm", stage="plan_generated", code=code)
    try:
        chunks = await _execute_plan(code, plan, user)
    except (PlanRejected, asyncio.TimeoutError, RetrievalUnavailable) as exc:
        await emit("rlm", stage="plan_failed", reason=repr(exc), fallback="default plan")
        errors.append(f"search plan failed ({type(exc).__name__}); used default plan")
        chunks = await _execute_plan(_default_plan(plan.rewritten_query, plan), plan, user)
    await emit("rlm", stage="plan_executed", chunks=len(chunks), documents=len({c["doc_id"] for c in chunks}))

    if not chunks:
        return {"chunks": [], "research": {"findings": [], "stats": {"documents": 0}}, "errors": errors}

    # 2-5. decompose, sub-agents, recursive aggregation
    docs = group_by_document(chunks, settings.rlm_max_docs)
    findings, stats = await map_reduce(docs, plan.rewritten_query)

    # 6. structured analysis (analyst/admin only - registry enforces it)
    tool_results = list(state.get("tool_results", []))
    if any(t.name == "python_analysis" for t in plan.tools):
        evidence_chunks = [c for ch in docs.values() for c in ch]
        for t in (t for t in plan.tools if t.name == "python_analysis"):
            tool_results.append(await registry.call(user, t.name, t.args, data=evidence_chunks))
        errors += [f"{r['tool']} {r['status']}: {r['error']}" for r in tool_results if r["status"] != "ok"]

    cited = {e for f in findings.findings for e in f.evidence}
    evidence = [c for ch in docs.values() for c in ch if c["chunk_id"] in cited] or [ch[0] for ch in docs.values()]
    return {"chunks": evidence, "tool_results": tool_results, "errors": errors,
            "research": {"findings": [f.model_dump() for f in findings.findings], "notes": findings.notes, "stats": stats,
                         "documents": [{"doc_id": d, "title": c[0]["title"]} for d, c in docs.items()]}}
