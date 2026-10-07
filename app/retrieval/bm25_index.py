"""Sparse (keyword) retrieval with BM25. The chunk store is persisted next to the Pinecone index."""
import json
import re
from typing import Callable

from rank_bm25 import BM25Okapi

from app.config import settings

_STOP = {"the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "is", "are", "was", "were", "what", "which", "with", "by", "all", "me"}


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOP]


def chunks_path():
    return settings.index_dir / "chunks.json"


class BM25Index:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self._bm25 = BM25Okapi([tokenize(f"{c['title']} {c['text']}") for c in chunks]) if chunks else None

    @classmethod
    def load(cls) -> "BM25Index":
        path = chunks_path()
        return cls(json.loads(path.read_text()) if path.exists() else [])

    @staticmethod
    def save(chunks: list[dict]) -> None:
        settings.index_dir.mkdir(parents=True, exist_ok=True)
        chunks_path().write_text(json.dumps(chunks))

    def search(self, query: str, predicate: Callable[[dict], bool], k: int) -> list[tuple[dict, float]]:
        """BM25 over the whole corpus (stable IDF), then metadata/ACL filter, then top-k."""
        if not self._bm25:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(zip(self.chunks, scores), key=lambda x: x[1], reverse=True)
        return [(c, float(s)) for c, s in ranked if s > 0 and predicate(c)][:k]
