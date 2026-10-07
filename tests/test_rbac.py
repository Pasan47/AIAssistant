import asyncio

from pydantic import BaseModel

from app.auth import User
from app.permissions import Role, allowed_access_levels, is_tool_allowed
from app.tools.registry import ToolRegistry, ToolSpec


class Args(BaseModel):
    n: int = 1


async def _handler(args, user, data):
    return {"n": args.n}


def _registry():
    r = ToolRegistry()
    for name in ("python_analysis", "admin_reindex", "unlisted_tool"):
        r.register(ToolSpec(name, "t", Args, _handler, timeout_s=1))
    return r


def test_access_levels_by_role():
    assert allowed_access_levels(Role.VIEWER) == ["public", "internal"]
    assert "confidential" in allowed_access_levels(Role.ANALYST) and "restricted" not in allowed_access_levels(Role.ANALYST)
    assert "restricted" in allowed_access_levels(Role.ADMIN)


def test_tool_policy_default_deny():
    assert not is_tool_allowed(Role.VIEWER, "python_analysis")
    assert is_tool_allowed(Role.ANALYST, "python_analysis") and not is_tool_allowed(Role.ANALYST, "admin_reindex")
    assert not is_tool_allowed(Role.ADMIN, "unlisted_tool")


def test_registry_enforces_rbac_even_if_agent_requests_tool():
    r = _registry()
    viewer, admin = User("v", Role.VIEWER, "x"), User("a", Role.ADMIN, "x")
    assert asyncio.run(r.call(viewer, "admin_reindex", {}))["status"] == "denied"
    assert asyncio.run(r.call(admin, "admin_reindex", {"n": 3}))["output"] == {"n": 3}
    assert asyncio.run(r.call(admin, "unlisted_tool", {}))["status"] == "denied"   # not in policy -> denied
    assert asyncio.run(r.call(admin, "admin_reindex", {"n": "abc"}))["status"] == "invalid_args"


def test_registry_timeout_is_contained():
    r = ToolRegistry()

    async def slow(args, user, data):
        await asyncio.sleep(5)

    r.register(ToolSpec("python_analysis", "t", Args, slow, timeout_s=0.05))
    assert asyncio.run(r.call(User("a", Role.ADMIN, "x"), "python_analysis", {}))["status"] == "timeout"
