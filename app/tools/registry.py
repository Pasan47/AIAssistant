"""Tool registry = the ONLY path from an agent to a tool. Enforces, in order:
   existence -> RBAC (default deny) -> argument validation -> timeout -> error isolation.
The LLM can *request* a tool; this code decides whether it runs.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from langsmith import traceable
from pydantic import BaseModel, ValidationError

from app.auth import User
from app.config import settings
from app.context import emit
from app.permissions import Role, is_tool_allowed, tools_for

log = logging.getLogger(__name__)
Handler = Callable[[BaseModel, User, Any], Awaitable[Any]]


@dataclass
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Handler
    timeout_s: float = settings.tool_timeout_s


def _result(tool: str, status: str, output: Any = None, error: str | None = None) -> dict:
    return {"tool": tool, "status": status, "output": output, "error": error}


@traceable(run_type="tool", name="tool_call")
async def _execute(tool_name: str, spec: ToolSpec, args: BaseModel, user: User, data: Any) -> Any:
    return await asyncio.wait_for(spec.handler(args, user, data), spec.timeout_s)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def describe_for(self, role: Role) -> str:
        """Only advertise tools the role may use (smaller attack surface; enforcement still happens in call())."""
        lines = []
        for name in tools_for(role):
            if name in self._tools and name != "knowledge_search":
                fields = ", ".join(self._tools[name].args_model.model_fields)
                lines.append(f"- {name}({fields}): {self._tools[name].description}")
        return "\n".join(lines) or "(none)"

    async def call(self, user: User, name: str, raw_args: dict | None, data: Any = None) -> dict:
        spec = self._tools.get(name)
        if spec is None:
            return _result(name, "error", error="unknown tool")

        if not is_tool_allowed(user.role, name):
            log.warning("tool access denied", extra={"ctx": {"user": user.username, "role": user.role.value, "tool": name}})
            await emit("tool_denied", tool=name, role=user.role.value)
            return _result(name, "denied", error=f"Role '{user.role.value}' is not permitted to use '{name}'.")

        try:
            args = spec.args_model.model_validate(raw_args or {})
        except ValidationError as exc:
            await emit("tool_end", tool=name, status="invalid_args", ms=0)
            return _result(name, "invalid_args", error=str(exc.errors()[0]["msg"]))

        await emit("tool_start", tool=name, args=args.model_dump(exclude_none=True))
        t0 = time.perf_counter()
        try:
            output = await _execute(name, spec, args, user, data)
            status, res = "ok", _result(name, "ok", output)
        except asyncio.TimeoutError:
            status, res = "timeout", _result(name, "timeout", error=f"'{name}' timed out after {spec.timeout_s:.0f}s")
        except Exception as exc:  # noqa: BLE001 - a tool failure must not crash the agent turn
            log.exception("tool failed", extra={"ctx": {"tool": name}})
            status, res = "error", _result(name, "error", error=f"{type(exc).__name__}: {exc}"[:300])
        await emit("tool_end", tool=name, status=status, ms=int((time.perf_counter() - t0) * 1000))
        return res
