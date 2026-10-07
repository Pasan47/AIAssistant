"""Process-wide singletons (retriever, tool registry)."""
from functools import lru_cache

from app.retrieval.hybrid import HybridRetriever
from app.tools.builtin import build_registry
from app.tools.registry import ToolRegistry


@lru_cache
def get_retriever() -> HybridRetriever:
    return HybridRetriever()


@lru_cache
def get_registry() -> ToolRegistry:
    return build_registry()
