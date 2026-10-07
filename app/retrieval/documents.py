"""Load markdown documents (YAML front-matter) and turn them into attributed, metadata-rich chunks."""
import re
from pathlib import Path

import yaml

from app.config import settings
from app.retrieval.chunking import chunk_text

_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_EXTRA_FIELDS = ("service", "severity", "root_cause", "duration_minutes")
DOCUMENT_TYPES = ["incident", "runbook", "architecture", "product_spec", "policy", "meeting_notes"]


def date_to_int(date_str: str) -> int:
    """'2025-05-06' -> 20250506 (Pinecone range filters need numbers)."""
    return int(date_str.replace("-", ""))


def load_documents(directory: Path | None = None) -> list[dict]:
    docs = []
    for path in sorted((directory or settings.docs_dir).glob("*.md")):
        match = _FRONT.match(path.read_text(encoding="utf-8"))
        if not match:
            raise ValueError(f"{path.name}: missing YAML front-matter")
        meta = yaml.safe_load(match.group(1))
        docs.append({"meta": meta, "body": match.group(2)})
    return docs


def build_chunks(doc: dict) -> list[dict]:
    meta = doc["meta"]
    base = {
        "doc_id": meta["doc_id"],
        "title": meta["title"],
        "department": meta["department"],
        "document_type": meta["document_type"],
        "access_level": meta["access_level"],
        "created_date": str(meta["created_date"]),
        "created_int": date_to_int(str(meta["created_date"])),
        **{k: meta[k] for k in _EXTRA_FIELDS if k in meta},
    }
    pieces = chunk_text(
        doc["body"], settings.chunk_min_tokens, settings.chunk_max_tokens, settings.chunk_overlap_tokens
    )
    return [{**base, "chunk_id": f"{base['doc_id']}#{i}", "text": text} for i, text in enumerate(pieces, start=1)]
