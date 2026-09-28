"""
Thin proxy that delegates all DB operations to whatever backend is active.
Keeps the public API stable so tools.py, cli.py, etc. don't need to care
which engine is running underneath.
"""

from __future__ import annotations

import logging
from typing import Any

from db_mcp.backends import get_backend

log = logging.getLogger(__name__)


async def connect() -> None:
    await get_backend().connect()


async def close_pool() -> None:
    await get_backend().close()


async def execute_readonly_query(
    sql: str, params: list[Any] | None = None
) -> list[dict[str, Any]]:
    """Run a SELECT and return rows as dicts. Raises ValueError for non-SELECTs."""
    return await get_backend().execute_readonly_query(sql, params)


async def get_all_tables() -> list[dict[str, Any]]:
    return await get_backend().get_all_tables()


async def describe_table(table_name: str) -> dict[str, Any]:
    return await get_backend().describe_table(table_name)


async def get_schema_as_text() -> str:
    return await get_backend().get_schema_as_text()


async def check_db_health() -> dict[str, Any]:
    return await get_backend().check_health()


def get_dialect_name() -> str:
    return get_backend().dialect_name
