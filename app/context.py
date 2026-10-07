"""Request-scoped context shared by graph nodes without threading it through every signature.

* current_user    - the authenticated principal. Set by the API layer, NEVER by the LLM.
* current_emitter - pushes agent-activity events to the SSE stream (Streamlit activity panel).
"""
import time
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:  # avoid importing JWT machinery just for typing
    from app.auth import User

Emitter = Callable[[dict[str, Any]], Awaitable[None]]

current_user: ContextVar["User | None"] = ContextVar("current_user", default=None)
current_emitter: ContextVar[Emitter | None] = ContextVar("current_emitter", default=None)
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


async def emit(event_type: str, **data: Any) -> None:
    """Fire-and-forget activity event. Must never break the agent run."""
    emitter = current_emitter.get()
    if emitter is None:
        return
    try:
        await emitter({"type": event_type, "ts": time.time(), **data})
    except Exception:  # noqa: BLE001 - observability must not take the request down
        pass
