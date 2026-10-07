"""Ingestion CLI: python -m app.retrieval.ingest

Chunks documents, persists the BM25 chunk store, and (if keys are configured) embeds + upserts to Pinecone.
Without Pinecone/OpenAI keys it still builds the sparse index so the app runs in degraded (BM25-only) mode.
"""
import asyncio
import logging
from collections import defaultdict

from app.logging_conf import configure_logging
from app.retrieval.bm25_index import BM25Index
from app.retrieval.documents import build_chunks, load_documents
from app.retrieval.embeddings import get_embeddings
from app.retrieval.pinecone_store import PineconeStore
from app.config import settings

log = logging.getLogger("ingest")


async def ingest_documents() -> dict:
    chunks = [c for doc in load_documents() for c in build_chunks(doc)]
    BM25Index.save(chunks)
    summary = {"documents": len({c["doc_id"] for c in chunks}), "chunks": len(chunks), "pinecone": "skipped"}

    store = PineconeStore()
    if store.configured and settings.openai_api_key:
        by_ns: dict[str, list[dict]] = defaultdict(list)
        for c in chunks:
            by_ns[c["document_type"]].append(c)  # namespace == document_type
        for ns, items in by_ns.items():
            vectors = await get_embeddings().aembed_documents([f"{c['title']}\n{c['text']}" for c in items])
            await store.upsert(ns, items, vectors)
            log.info("upserted namespace", extra={"ctx": {"namespace": ns, "chunks": len(items)}})
        summary["pinecone"] = f"upserted into {len(by_ns)} namespaces"
    else:
        log.warning("Pinecone/OpenAI keys missing - BM25-only index built")
    return summary


if __name__ == "__main__":
    configure_logging()
    print(asyncio.run(ingest_documents()))
