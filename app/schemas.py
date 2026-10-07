"""Pydantic models for API payloads, supervisor plans and RLM findings (assumption: Pydantic everywhere)."""
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.retrieval.documents import DOCUMENT_TYPES

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ------------------------------------------------------------------ API
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=settings.max_message_chars)
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9\-]{8,64}$")


class FeedbackRequest(BaseModel):
    run_id: str = Field(min_length=8, max_length=64)
    score: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=500)


# ------------------------------------------------------------------ supervisor plan
class SearchFilters(BaseModel):
    department: str | None = None
    document_type: str | None = None
    date_from: str | None = None
    date_to: str | None = None

    @field_validator("document_type", mode="before")
    @classmethod
    def _valid_type(cls, v):  # LLM output is untrusted: drop anything outside the known namespaces
        return v if v in DOCUMENT_TYPES else None

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def _valid_date(cls, v):
        return v if isinstance(v, str) and _DATE.match(v) else None

    @field_validator("department", mode="before")
    @classmethod
    def _valid_dept(cls, v):
        return v.lower().strip() if isinstance(v, str) and re.fullmatch(r"[A-Za-z_ ]{2,30}", v) else None


class ToolRequest(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    intent: str = "knowledge_qa"
    route: Literal["retrieval", "research", "direct"] = "retrieval"
    rewritten_query: str
    filters: SearchFilters = Field(default_factory=SearchFilters)
    tools: list[ToolRequest] = Field(default_factory=list)
    sub_tasks: list[str] = Field(default_factory=list)
    reasoning: str = ""

    @field_validator("filters", mode="before")
    @classmethod
    def _none_filters(cls, v):
        return v or {}

    @field_validator("tools", "sub_tasks", mode="before")
    @classmethod
    def _none_list(cls, v):
        return v or []


# ------------------------------------------------------------------ RLM findings
class Finding(BaseModel):
    statement: str
    theme: str = ""
    evidence: list[str] = Field(default_factory=list)  # chunk_ids


class Findings(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    notes: str = ""
