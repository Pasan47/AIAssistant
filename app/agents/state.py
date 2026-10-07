"""Graph state. Everything here is JSON-serialisable so the checkpointer can persist it per session."""
from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # ---- persists across turns (session memory, via checkpointer thread_id) ----
    messages: Annotated[list, add_messages]   # conversation history
    memory: dict[str, Any]                     # asked_questions, topics, user_context, turns

    # ---- per-turn working data (reset by the API on every request) ----
    question: str
    blocked: bool
    plan: dict[str, Any]                       # supervisor output (Plan.model_dump())
    chunks: list[dict]                         # evidence the answer may cite
    tool_results: list[dict]
    research: dict[str, Any]                   # RLM output
    draft: str
    final: str
    sources: list[dict]
    validation: dict[str, Any]
    errors: list[str]                          # contained failures (degradation notes)


def fresh_turn(question: str) -> dict:
    return {"question": question, "blocked": False, "plan": {}, "chunks": [], "tool_results": [], "research": {},
            "draft": "", "final": "", "sources": [], "validation": {}, "errors": []}
