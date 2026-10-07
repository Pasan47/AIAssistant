"""Simple MCP server (stdio) exposing dummy enterprise data. Run standalone: python -m app.mcp_server.server"""
from mcp.server.fastmcp import FastMCP

from app.mcp_server.data import EMPLOYEES, INCIDENTS, SERVICES

mcp = FastMCP("meridian-enterprise")


@mcp.tool()
def employee_lookup(query: str) -> list[dict]:
    """Search the employee directory by name, title or team."""
    q = query.lower()
    return [e for e in EMPLOYEES if q in " ".join(str(v) for v in e.values()).lower()]


@mcp.tool()
def service_catalog(name: str | None = None, team: str | None = None) -> list[dict]:
    """List services, optionally filtered by name or owning team."""
    return [s for s in SERVICES if (not name or s["name"] == name) and (not team or s["team"] == team.lower())]


@mcp.tool()
def incident_records(service: str | None = None, severity: str | None = None) -> list[dict]:
    """Return incident records from the incident tracker."""
    return [i for i in INCIDENTS if (not service or i["service"] == service) and (not severity or i["severity"] == severity)]


if __name__ == "__main__":
    mcp.run()  # stdio transport
