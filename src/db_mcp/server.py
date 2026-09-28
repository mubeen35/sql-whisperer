"""
MCP Server entry point.

Wires up the MCPServer, registers tools/resources/prompts, and handles
transport (stdio for Claude Desktop / Cursor, SSE for HTTP clients).

NOTE: never print() in this module — stdout is the MCP JSON-RPC stream.
All logging goes to stderr.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import structlog
from mcp.server.mcpserver import MCPServer

from db_mcp.config import get_settings
from db_mcp.database import close_pool, get_dialect_name
from db_mcp.ollama_client import close_client
from db_mcp.tools import register_tools
from db_mcp.resources import register_resources
from db_mcp.prompts import register_prompts


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


def create_app() -> MCPServer:
    settings = get_settings()
    _configure_logging(settings.log_level)

    log = logging.getLogger(__name__)
    dialect = get_dialect_name()

    log.info(
        "Starting Database MCP Server",
        extra={
            "db_type": settings.db_type,
            "db_host": settings.db_host,
            "db_name": settings.db_name,
            "ollama_model": settings.ollama_model,
            "transport": settings.mcp_transport,
        },
    )

    mcp = MCPServer(
        name="Database Assistant",
        instructions=(
            f"A {dialect} database assistant powered by Ollama. "
            "Use list_tables to explore the schema, describe_table for details, "
            "execute_sql for direct queries, and ask_database for natural language questions."
        ),
    )

    register_tools(mcp)
    register_resources(mcp)
    register_prompts(mcp)

    return mcp


async def _shutdown() -> None:
    await close_pool()
    await close_client()


def main() -> None:
    settings = get_settings()
    app = create_app()

    try:
        if settings.mcp_transport == "sse":
            app.run(transport="sse", host=settings.mcp_host, port=settings.mcp_port)
        else:
            app.run(transport="stdio")
    finally:
        asyncio.run(_shutdown())


if __name__ == "__main__":
    main()
