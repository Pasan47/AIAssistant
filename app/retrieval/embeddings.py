from functools import lru_cache

from langchain_openai import OpenAIEmbeddings

from app.config import settings


@lru_cache
def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key or None, timeout=30, max_retries=2)
