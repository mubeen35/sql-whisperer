"""Abstract base for all database backends."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

log = logging.getLogger(__name__)


class DatabaseBackend(ABC):
    """
    Interface that each DB engine must implement (asyncpg, aiomysql, etc.).
    The rest of the app talks through this so it stays DB-agnostic.
    """

    dialect_name: str = "SQL"

    @abstractmethod
    async def connect(self) -> None:
        """Open a connection or pool."""

    @abstractmethod
    async def close(self) -> None:
        """Close the connection / pool."""

    @abstractmethod
    async def execute_readonly_query(
        self, sql: str, params: list[Any] | None = None
    ) -> list[dict[str, Any]]:
        """
        Run a SELECT and return rows as dicts.
        Must reject non-SELECTs before they reach the DB.
        """

    @abstractmethod
    async def get_all_tables(self) -> list[dict[str, Any]]:
        """Return all user tables/views. Each dict has: schema, name, type, approx_rows."""

    @abstractmethod
    async def describe_table(self, table_name: str) -> dict[str, Any]:
        """Return column metadata: columns, primary_keys, foreign_keys, indexes."""

    @abstractmethod
    async def get_schema_as_text(self) -> str:
        """Full schema as a readable text block."""

    @abstractmethod
    async def check_health(self) -> dict[str, Any]:
        """Return {"status": "ok", ...} or {"status": "error", "error": "..."}."""

    @staticmethod
    def validate_select(sql: str) -> None:
        """Raise ValueError if this isn't a SELECT."""
        stripped = sql.strip().upper()
        bad = ("INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE", "GRANT")
        if any(stripped.startswith(kw) for kw in bad):
            raise ValueError(f"Only SELECT queries are allowed. Got: {sql.strip()[:80]}")
