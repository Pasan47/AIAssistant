"""Strict argument models: tool parameters are validated BEFORE execution (LLM output is untrusted)."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas import SearchFilters

ANALYSIS_FIELDS = {"root_cause", "severity", "service", "department", "document_type", "duration_minutes"}


class KnowledgeSearchArgs(SearchFilters):
    query: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=6, ge=1, le=15)


class EmployeeLookupArgs(BaseModel):
    query: str = Field(min_length=2, max_length=100, pattern=r"^[\w .\-@']+$")


class ServiceCatalogArgs(BaseModel):
    name: str | None = Field(default=None, max_length=60, pattern=r"^[\w\-]+$")
    team: str | None = Field(default=None, max_length=60, pattern=r"^[\w \-]+$")


class IncidentRecordsArgs(BaseModel):
    service: str | None = Field(default=None, max_length=60, pattern=r"^[\w\-]+$")
    severity: Literal["SEV1", "SEV2", "SEV3"] | None = None


class AnalysisArgs(BaseModel):
    operation: Literal["count_by", "stats", "monthly_trend"]
    field: str | None = None

    @field_validator("field")
    @classmethod
    def _whitelisted(cls, v):
        if v is not None and v not in ANALYSIS_FIELDS:
            raise ValueError(f"field must be one of {sorted(ANALYSIS_FIELDS)}")
        return v


class EmptyArgs(BaseModel):
    pass
