"""Concrete tools + registry factory. Handlers receive (validated_args, user, server_side_data)."""
import asyncio
import statistics
from collections import Counter

from app.config import settings
from app.mcp_server.client import MCP_TIMEOUT_S, call_mcp_tool
from app.tools.registry import ToolRegistry, ToolSpec
from app.tools.schemas import (AnalysisArgs, EmployeeLookupArgs, EmptyArgs, IncidentRecordsArgs,
                               KnowledgeSearchArgs, ServiceCatalogArgs)


# ---------------------------------------------------------------- knowledge search
async def _knowledge_search(args: KnowledgeSearchArgs, user, _data):
    from app.services import get_retriever  # late import avoids cycles

    return await get_retriever().search(
        user, args.query, args.department, args.document_type, args.date_from, args.date_to, args.top_k
    )


# ---------------------------------------------------------------- python analysis
def analyze(args: AnalysisArgs, chunks: list[dict]) -> dict:
    """Structured analysis over server-supplied retrieved data (the LLM never injects the dataset)."""
    docs = list({c["doc_id"]: c for c in chunks}.values())  # one row per document
    if args.operation == "count_by":
        field = args.field or "root_cause"
        counts = Counter(str(d.get(field, "unknown")) for d in docs)
        return {"operation": "count_by", "field": field, "total_documents": len(docs),
                "counts": [{"value": k, "documents": v} for k, v in counts.most_common()]}
    if args.operation == "stats":
        field = args.field or "duration_minutes"
        values = [float(d[field]) for d in docs if isinstance(d.get(field), (int, float))]
        if not values:
            return {"operation": "stats", "field": field, "error": "no numeric values"}
        return {"operation": "stats", "field": field, "count": len(values), "mean": round(statistics.mean(values), 1),
                "median": statistics.median(values), "min": min(values), "max": max(values)}
    trend = Counter(d["created_date"][:7] for d in docs)  # monthly_trend
    return {"operation": "monthly_trend", "months": [{"month": m, "documents": n} for m, n in sorted(trend.items())]}


async def _python_analysis(args: AnalysisArgs, _user, data):
    return await asyncio.to_thread(analyze, args, data or [])


# ---------------------------------------------------------------- MCP-backed tools
def _mcp_handler(mcp_name: str):
    async def handler(args, _user, _data):
        return await asyncio.wait_for(call_mcp_tool(mcp_name, args.model_dump(exclude_none=True)), MCP_TIMEOUT_S)

    return handler


# ---------------------------------------------------------------- admin
async def _admin_reindex(_args, _user, _data):
    from app.retrieval.ingest import ingest_documents
    from app.services import get_retriever

    summary = await ingest_documents()
    get_retriever().reload()
    return summary


def build_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(ToolSpec("knowledge_search", "Hybrid search over indexed documents.", KnowledgeSearchArgs, _knowledge_search))
    r.register(ToolSpec("python_analysis", "Count/stats/trend analysis over retrieved documents (operation: count_by|stats|monthly_trend, field).",
                        AnalysisArgs, _python_analysis))
    r.register(ToolSpec("employee_lookup", "MCP: employee directory (owners, on-call).", EmployeeLookupArgs, _mcp_handler("employee_lookup"), MCP_TIMEOUT_S + 5))
    r.register(ToolSpec("service_catalog", "MCP: service catalog (owner, tier, runbook).", ServiceCatalogArgs, _mcp_handler("service_catalog"), MCP_TIMEOUT_S + 5))
    r.register(ToolSpec("incident_records", "MCP: live incident tracker records.", IncidentRecordsArgs, _mcp_handler("incident_records"), MCP_TIMEOUT_S + 5))
    r.register(ToolSpec("admin_reindex", "ADMIN: rebuild the knowledge index.", EmptyArgs, _admin_reindex, 300))
    return r
