"""Central, environment-driven configuration (every assumption in assumption.docx is a knob here)."""
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Export .env into os.environ so LangChain / LangSmith / OpenAI SDKs pick their variables up.
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bank_name: str = "Meridian Commercial Bank"
    log_level: str = "INFO"

    # LLM (assumption: OpenAI; provider is isolated behind app/llm.py)
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    llm_timeout_s: float = 45.0

    # Pinecone
    pinecone_api_key: str = ""
    pinecone_index: str = "meridian-kb"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"

    # Retrieval (assumption: 500-800 token chunks, 60% dense / 40% BM25)
    docs_dir: Path = PROJECT_ROOT / "data" / "docs"
    index_dir: Path = PROJECT_ROOT / "data" / "index"
    chunk_min_tokens: int = 500
    chunk_max_tokens: int = 800
    chunk_overlap_tokens: int = 80
    dense_weight: float = 0.6
    sparse_weight: float = 0.4
    top_k: int = 6
    candidate_k: int = 20
    rerank_enabled: bool = True

    # Recursive Language Model (research agent)
    rlm_batch_size: int = 3          # documents per sub-agent
    rlm_fan_in: int = 3              # partial results merged per reduce step
    rlm_max_depth: int = 3           # recursion guard for the reduce tree
    rlm_max_docs: int = 30
    rlm_max_search_calls: int = 8
    rlm_concurrency: int = 3
    rlm_plan_timeout_s: float = 40.0

    # Security / platform
    jwt_secret: str = "dev-only-secret"
    jwt_ttl_minutes: int = 120
    max_message_chars: int = 2000
    rate_limit_capacity: int = 10
    rate_limit_refill_per_sec: float = 0.2
    tool_timeout_s: float = 25.0
    mcp_timeout_s: float = 15.0
    request_timeout_s: float = 180.0
    memory_window: int = 6           # messages replayed to the LLM each turn


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
