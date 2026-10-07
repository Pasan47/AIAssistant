"""Node wrapper: emits live activity events, times the node, and CONTAINS failures.

Butterfly-effect control: a node that raises never kills the turn. The error is recorded in state.errors,
a safe fallback patch is applied, and downstream nodes see the degradation and adapt (e.g. the response
agent states which evidence is missing).
"""
import functools
import logging
import time
from typing import Awaitable, Callable

from app.context import emit

log = logging.getLogger(__name__)


def agent_node(name: str, label: str, fallback: dict | None = None):
    def decorator(fn: Callable[[dict], Awaitable[dict]]):
        @functools.wraps(fn)
        async def wrapper(state: dict) -> dict:
            await emit("node_start", node=name, label=label)
            t0 = time.perf_counter()
            try:
                patch, status = await fn(state), "ok"
            except Exception as exc:  # noqa: BLE001
                log.exception("node failed", extra={"ctx": {"node": name}})
                await emit("error", node=name, message=f"{type(exc).__name__}: {str(exc)[:200]}")
                patch = {"errors": [*state.get("errors", []), f"{name} failed ({type(exc).__name__})"], **(fallback or {})}
                status = "error"
            await emit("node_end", node=name, status=status, ms=int((time.perf_counter() - t0) * 1000))
            return patch

        return wrapper

    return decorator
