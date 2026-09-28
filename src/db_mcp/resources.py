"""MCP Resources — read-only data endpoints exposed by the server."""

from __future__ import annotations

import json
import logging

from mcp.server.mcpserver import MCPServer

from db_mcp.database import get_all_tables, describe_table, get_schema_as_text

log = logging.getLogger(__name__)


def register_resources(mcp: MCPServer) -> None:

    @mcp.resource("schema://tables")
    async def resource_list_tables() -> str:
        """JSON list of all tables/views with schema, name, type, approx_rows."""
        tables = await get_all_tables()
        return json.dumps(tables, indent=2, default=str)

    @mcp.resource("schema://full")
    async def resource_full_schema() -> str:
        """Full database schema as readable text."""
        return await get_schema_as_text()

    @mcp.resource("schema://table/{table_name}")
    async def resource_describe_table(table_name: str) -> str:
        """Column metadata for a specific table as JSON."""
        try:
            info = await describe_table(table_name)
            return json.dumps(info, indent=2, default=str)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
