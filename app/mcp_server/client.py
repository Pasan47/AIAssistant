"""MCP client: spawns the stdio server and calls one tool. Failures bubble up to the registry (isolated there)."""
import json
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.config import PROJECT_ROOT, settings


async def call_mcp_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
    params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server.server"], cwd=str(PROJECT_ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
    if result.isError:
        raise RuntimeError(f"MCP tool '{name}' returned an error")
    out: list[Any] = []
    for part in result.content:
        text = getattr(part, "text", None)
        if text is None:
            continue
        try:
            out.append(json.loads(text))
        except json.JSONDecodeError:
            out.append(text)
    return out


MCP_TIMEOUT_S = settings.mcp_timeout_s
