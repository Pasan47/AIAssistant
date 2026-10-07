"""Single seam to the LLM provider (assumption: OpenAI; swap this file to change vendor).

All failures surface as LLMUnavailable so every caller has ONE exception to degrade on.
"""
import json
import logging
from functools import lru_cache
from typing import AsyncIterator, TypeVar

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.errors import LLMUnavailable

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


@lru_cache
def _chat() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.llm_model,
        temperature=0,
        timeout=settings.llm_timeout_s,
        max_retries=2,  # transient errors / 429s retried with backoff by the SDK
        api_key=settings.openai_api_key or None,
    )


async def llm_text(system: str, user: str) -> str:
    try:
        resp = await _chat().ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        return str(resp.content)
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable(repr(exc)) from exc


async def llm_stream(messages: list[BaseMessage]) -> AsyncIterator[str]:
    try:
        async for chunk in _chat().astream(messages):
            if chunk.content:
                yield str(chunk.content)
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable(repr(exc)) from exc


async def llm_json(system: str, user: str, schema: type[T]) -> T:
    """JSON-mode call validated against a Pydantic schema; one repair retry on malformed output."""
    model = _chat().bind(response_format={"type": "json_object"})
    last_err = ""
    for attempt in range(2):
        prompt = user if attempt == 0 else f"{user}\n\nYour previous reply was invalid ({last_err}). Return valid JSON only."
        try:
            resp = await model.ainvoke([SystemMessage(content=system), HumanMessage(content=prompt)])
        except Exception as exc:  # noqa: BLE001
            raise LLMUnavailable(repr(exc)) from exc
        try:
            return schema.model_validate(json.loads(str(resp.content)))
        except (json.JSONDecodeError, ValidationError) as exc:
            last_err = str(exc)[:200]
            log.warning("LLM returned invalid JSON", extra={"ctx": {"schema": schema.__name__, "error": last_err}})
    raise LLMUnavailable(f"invalid structured output for {schema.__name__}")
