"""Pure RBAC policy: who may see which documents and call which tools. No I/O, easy to unit test."""
from enum import Enum


class Role(str, Enum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    ADMIN = "admin"


# Ordered low -> high. A role may read documents up to (and including) its ceiling.
ACCESS_LEVELS = ["public", "internal", "confidential", "restricted"]
ROLE_MAX_LEVEL = {
    Role.VIEWER: "internal",
    Role.ANALYST: "confidential",
    Role.ADMIN: "restricted",
}

# Default-deny: a tool not listed here is callable by nobody.
ALL_ROLES = {Role.VIEWER, Role.ANALYST, Role.ADMIN}
TOOL_PERMISSIONS: dict[str, set[Role]] = {
    "knowledge_search": ALL_ROLES,
    "python_analysis": {Role.ANALYST, Role.ADMIN},
    "employee_lookup": {Role.ANALYST, Role.ADMIN},   # MCP
    "service_catalog": {Role.ANALYST, Role.ADMIN},   # MCP
    "incident_records": {Role.ANALYST, Role.ADMIN},  # MCP
    "admin_reindex": {Role.ADMIN},
}


def allowed_access_levels(role: Role) -> list[str]:
    ceiling = ACCESS_LEVELS.index(ROLE_MAX_LEVEL[role])
    return ACCESS_LEVELS[: ceiling + 1]


def is_tool_allowed(role: Role, tool: str) -> bool:
    return role in TOOL_PERMISSIONS.get(tool, set())


def tools_for(role: Role) -> list[str]:
    return [t for t, roles in TOOL_PERMISSIONS.items() if role in roles]
