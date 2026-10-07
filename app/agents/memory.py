"""Memory update node (session memory, LangGraph checkpointer keyed by session_id = thread_id).

Design (see README): three layers, all inside the persisted graph state so they survive turns of a session:
  * messages  - raw conversation; the last N are replayed to the supervisor/response agents
  * memory    - compact structured memory: previous questions, topics, user context (cheap, no extra LLM call)
  * checkpoint- MemorySaver keeps the whole state per thread. Long-term (cross-session) memory = store swap.
"""
from app.agents.runtime import agent_node
from app.context import current_user, emit

MAX_QUESTIONS = 10


@agent_node("memory_update", "Updating session memory")
async def memory_update(state: dict) -> dict:
    user = current_user.get()
    mem = dict(state.get("memory") or {})
    plan = state.get("plan", {})

    questions = [*mem.get("asked_questions", []), state["question"][:200]][-MAX_QUESTIONS:]
    topics = list(mem.get("topics", []))
    for t in (plan.get("filters") or {}).values():
        if isinstance(t, str) and t[:4] != "202" and t not in topics:
            topics.append(t)
    mem.update(
        asked_questions=questions,
        topics=topics[-10:],
        user_context={"username": user.username, "role": user.role.value, "department": user.department},
        turns=mem.get("turns", 0) + 1,
        last_docs=[s["doc_id"] for s in state.get("sources", [])][:5],
    )
    await emit("memory", turns=mem["turns"], remembered_questions=len(questions), topics=mem["topics"], last_docs=mem["last_docs"])
    return {"memory": mem}
