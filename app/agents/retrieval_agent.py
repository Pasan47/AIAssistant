"""Retrieval Agent: RAG over the hybrid index + any enterprise/analysis tools the supervisor requested.
Every tool goes through the registry (RBAC, validation, timeout); this agent has no direct tool access."""
import asyncio

from app.agents.runtime import agent_node
from app.context import current_user, emit
from app.schemas import Plan
from app.services import get_registry

_ANALYSIS = "python_analysis"


@agent_node("retrieval", "Searching knowledge base and tools", fallback={"chunks": [], "tool_results": []})
async def retrieval_agent(state: dict) -> dict:
    user, registry = current_user.get(), get_registry()
    plan = Plan.model_validate(state["plan"])
    errors = list(state.get("errors", []))

    search_args = {"query": plan.rewritten_query, **plan.filters.model_dump(exclude_none=True)}
    other = [t for t in plan.tools if t.name != _ANALYSIS]
    analysis = [t for t in plan.tools if t.name == _ANALYSIS]

    # knowledge search and enterprise (MCP) tools are independent -> run concurrently
    search_res, *tool_res = await asyncio.gather(
        registry.call(user, "knowledge_search", search_args),
        *(registry.call(user, t.name, t.args) for t in other),
    )
    chunks: list[dict] = []
    if search_res["status"] == "ok":
        chunks = search_res["output"]["chunks"]
        if search_res["output"]["degraded"]:
            errors.append(f"retrieval degraded: {', '.join(search_res['output']['degraded'])}")
    else:
        errors.append(f"knowledge_search {search_res['status']}: {search_res['error']}")
        await emit("degraded", node="retrieval", message="Knowledge search unavailable; answering without documents")

    # analysis depends on retrieved data, which is supplied server-side (never by the LLM)
    for t in analysis:
        tool_res.append(await registry.call(user, t.name, t.args, data=chunks))

    for r in tool_res:
        if r["status"] != "ok":
            errors.append(f"{r['tool']} {r['status']}: {r['error']}")
    return {"chunks": chunks, "tool_results": tool_res, "errors": errors}
