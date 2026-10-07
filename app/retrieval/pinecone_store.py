"""Pinecone dense store. One NAMESPACE per document_type; ACL/date/department via METADATA filters."""
import asyncio
import time

from pinecone import Pinecone, ServerlessSpec

from app.config import settings


class PineconeStore:
    def __init__(self) -> None:
        self._index = None

    @property
    def configured(self) -> bool:
        return bool(settings.pinecone_api_key)

    def _get_index(self):
        if self._index is None:
            pc = Pinecone(api_key=settings.pinecone_api_key)
            if not pc.has_index(settings.pinecone_index):
                pc.create_index(
                    name=settings.pinecone_index,
                    dimension=settings.embedding_dim,
                    metric="cosine",
                    spec=ServerlessSpec(cloud=settings.pinecone_cloud, region=settings.pinecone_region),
                )
                while not pc.describe_index(settings.pinecone_index).status["ready"]:
                    time.sleep(1)
            self._index = pc.Index(settings.pinecone_index)
        return self._index

    async def upsert(self, namespace: str, chunks: list[dict], vectors: list[list[float]]) -> None:
        records = [{"id": c["chunk_id"], "values": v, "metadata": c} for c, v in zip(chunks, vectors)]

        def _do() -> None:
            index = self._get_index()
            for i in range(0, len(records), 100):
                index.upsert(vectors=records[i : i + 100], namespace=namespace)

        await asyncio.to_thread(_do)

    async def query(self, namespace: str, vector: list[float], flt: dict, top_k: int) -> list[tuple[dict, float]]:
        def _do():
            resp = self._get_index().query(
                vector=vector, top_k=top_k, namespace=namespace, filter=flt, include_metadata=True
            )
            return [(dict(m.metadata), float(m.score)) for m in resp.matches]

        return await asyncio.to_thread(_do)
