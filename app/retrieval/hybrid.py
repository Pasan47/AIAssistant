"""Hybrid retriever: dense (Pinecone) + sparse (BM25) -> normalised weighted fusion -> light rerank.

SECURITY: access-level filtering happens HERE, in code, from the authenticated user's role.
Agent-supplied filters (department, type, dates) can only narrow the result, never widen it.
"""
import asyncio
import logging

from langsmith import traceable

from app.auth import User
from app.config import settings
from app.context import emit
from app.errors import RetrievalUnavailable
from app.permissions import allowed_access_levels
from app.retrieval.bm25_index import BM25Index, tokenize
from app.retrieval.documents import DOCUMENT_TYPES, date_to_int
from app.retrieval.embeddings import get_embeddings
from app.retrieval.pinecone_store import PineconeStore

log = logging.getLogger(__name__)


def _normalise(scored: list[tuple[dict, float]]) -> dict[str, float]:
    """Min-max scale to [0,1] so cosine scores and BM25 scores are comparable."""
    if not scored:
        return {}
    values = [s for _, s in scored]
    lo, hi = min(values), max(values)
    return {c["chunk_id"]: (1.0 if hi == lo else (s - lo) / (hi - lo)) for c, s in scored}


class HybridRetriever:
    def __init__(self, store: PineconeStore | None = None, bm25: BM25Index | None = None) -> None:
        self.store = store or PineconeStore()
        self.bm25 = bm25 or BM25Index.load()

    def reload(self) -> None:
        self.bm25 = BM25Index.load()

    # -------------------------------------------------------------- filters
    @staticmethod
    def _pinecone_filter(levels, department, d_from, d_to) -> dict:
        flt: dict = {"access_level": {"$in": levels}}
        if department:
            flt["department"] = {"$eq": department}
        if d_from or d_to:
            flt["created_int"] = {
                **({"$gte": date_to_int(d_from)} if d_from else {}),
                **({"$lte": date_to_int(d_to)} if d_to else {}),
            }
        return flt

    @staticmethod
    def _predicate(levels, department, dtype, d_from, d_to):
        lo = date_to_int(d_from) if d_from else None
        hi = date_to_int(d_to) if d_to else None

        def ok(c: dict) -> bool:
            return (
                c["access_level"] in levels
                and (not department or c["department"] == department)
                and (not dtype or c["document_type"] == dtype)
                and (lo is None or c["created_int"] >= lo)
                and (hi is None or c["created_int"] <= hi)
            )

        return ok

    # -------------------------------------------------------------- legs
    async def _dense(self, query, levels, department, dtype, d_from, d_to) -> list[tuple[dict, float]]:
        if not self.store.configured:
            raise RetrievalUnavailable("Pinecone is not configured")
        vector = await get_embeddings().aembed_query(query)
        flt = self._pinecone_filter(levels, department, d_from, d_to)
        namespaces = [dtype] if dtype in DOCUMENT_TYPES else DOCUMENT_TYPES  # namespace per document type
        results = await asyncio.gather(
            *(self.store.query(ns, vector, flt, settings.candidate_k) for ns in namespaces), return_exceptions=True
        )
        merged, failures = [], 0
        for r in results:
            if isinstance(r, Exception):
                failures += 1
                log.warning("pinecone namespace query failed", extra={"ctx": {"error": repr(r)}})
            else:
                merged.extend(r)
        if failures == len(namespaces):
            raise RetrievalUnavailable("all Pinecone namespace queries failed")
        return sorted(merged, key=lambda x: x[1], reverse=True)[: settings.candidate_k]

    async def _sparse(self, query, predicate) -> list[tuple[dict, float]]:
        return await asyncio.to_thread(self.bm25.search, query, predicate, settings.candidate_k)

    # -------------------------------------------------------------- public
    @traceable(run_type="retriever", name="hybrid_search")
    async def search(
        self,
        user: User,
        query: str,
        department: str | None = None,
        document_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        top_k: int | None = None,
    ) -> dict:
        top_k = top_k or settings.top_k
        levels = allowed_access_levels(user.role)
        await emit("retrieval", status="started", query=query, allowed_levels=levels,
                   filters={"department": department, "document_type": document_type, "from": date_from, "to": date_to})

        dense_r, sparse_r = await asyncio.gather(
            self._dense(query, levels, department, document_type, date_from, date_to),
            self._sparse(query, self._predicate(levels, department, document_type, date_from, date_to)),
            return_exceptions=True,
        )
        degraded: list[str] = []
        if isinstance(dense_r, Exception):
            degraded.append("dense_unavailable")
            log.warning("dense retrieval failed; falling back to BM25", extra={"ctx": {"error": repr(dense_r)}})
            dense_r = []
        if isinstance(sparse_r, Exception):
            degraded.append("sparse_unavailable")
            log.warning("sparse retrieval failed", extra={"ctx": {"error": repr(sparse_r)}})
            sparse_r = []
        if len(degraded) == 2:
            raise RetrievalUnavailable("dense and sparse retrieval both failed")

        dense_n, sparse_n = _normalise(dense_r), _normalise(sparse_r)
        by_id = {c["chunk_id"]: c for c, _ in [*dense_r, *sparse_r]}
        fused = []
        for cid, chunk in by_id.items():
            d, s = dense_n.get(cid, 0.0), sparse_n.get(cid, 0.0)
            fused.append({**chunk, "dense_score": round(d, 4), "sparse_score": round(s, 4),
                          "score": round(settings.dense_weight * d + settings.sparse_weight * s, 4)})
        fused.sort(key=lambda c: c["score"], reverse=True)
        ranked = self._rerank(query, fused[: settings.candidate_k]) if settings.rerank_enabled else fused
        chunks = ranked[:top_k]

        await emit("retrieval", status="completed", hits=len(chunks), degraded=degraded,
                   dense_candidates=len(dense_r), sparse_candidates=len(sparse_r),
                   documents=sorted({c["doc_id"] for c in chunks}))
        return {"chunks": chunks, "degraded": degraded}

    @staticmethod
    def _rerank(query: str, candidates: list[dict]) -> list[dict]:
        """Light lexical rerank (query-term coverage in title+text). Swap for a cross-encoder in production."""
        terms = set(tokenize(query))
        if not terms:
            return candidates
        for c in candidates:
            hay = set(tokenize(f"{c['title']} {c['text']}"))
            c["score"] = round(0.8 * c["score"] + 0.2 * len(terms & hay) / len(terms), 4)
        return sorted(candidates, key=lambda c: c["score"], reverse=True)
