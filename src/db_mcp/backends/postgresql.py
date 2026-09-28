"""PostgreSQL backend using asyncpg."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import asyncpg

from db_mcp.backends.base import DatabaseBackend
from db_mcp.config import get_settings

log = logging.getLogger(__name__)


class PostgreSQLBackend(DatabaseBackend):

    dialect_name = "PostgreSQL"

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None
        self._pool_lock = asyncio.Lock()

    async def connect(self) -> None:
        async with self._pool_lock:
            if self._pool is None:
                s = get_settings()
                log.info("Creating asyncpg pool",
                         extra={"host": s.db_host, "port": s.db_port, "database": s.db_name})
                self._pool = await asyncpg.create_pool(
                    dsn=s.db_dsn,
                    min_size=s.db_min_pool_size,
                    max_size=s.db_max_pool_size,
                    command_timeout=30,
                    statement_cache_size=100,
                )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            log.info("PostgreSQL pool closed")

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            await self.connect()
        assert self._pool is not None
        return self._pool

    async def execute_readonly_query(
        self, sql: str, params: list[Any] | None = None
    ) -> list[dict[str, Any]]:
        self.validate_select(sql)

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SET LOCAL TRANSACTION READ ONLY")
                if params:
                    rows = await conn.fetch(sql, *params)
                else:
                    rows = await conn.fetch(sql)
                return [dict(row) for row in rows]

    async def get_all_tables(self) -> list[dict[str, Any]]:
        sql = """
            SELECT
                table_schema  AS schema,
                table_name    AS name,
                table_type    AS type
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY table_schema, table_name
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)
            result = []
            for row in rows:
                d = dict(row)
                try:
                    stat = await conn.fetchrow(
                        "SELECT reltuples::BIGINT AS approx_rows FROM pg_class WHERE relname = $1",
                        d["name"],
                    )
                    d["approx_rows"] = stat["approx_rows"] if stat else -1
                except Exception:
                    d["approx_rows"] = -1
                result.append(d)
            return result

    async def describe_table(self, table_name: str) -> dict[str, Any]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            columns = await conn.fetch(
                """
                SELECT
                    column_name, data_type, character_maximum_length,
                    numeric_precision, is_nullable, column_default, ordinal_position
                FROM information_schema.columns
                WHERE table_name = $1
                  AND table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY ordinal_position
                """,
                table_name,
            )
            if not columns:
                raise ValueError(f"Table '{table_name}' not found in the database.")

            pks = await conn.fetch(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema    = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                  AND tc.table_name      = $1
                ORDER BY kcu.ordinal_position
                """,
                table_name,
            )

            fks = await conn.fetch(
                """
                SELECT
                    kcu.column_name,
                    ccu.table_name  AS foreign_table,
                    ccu.column_name AS foreign_column
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema    = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema    = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_name      = $1
                """,
                table_name,
            )

            indexes = await conn.fetch(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = $1
                ORDER BY indexname
                """,
                table_name,
            )

            return {
                "table_name": table_name,
                "columns": [dict(c) for c in columns],
                "primary_keys": [pk["column_name"] for pk in pks],
                "foreign_keys": [dict(fk) for fk in fks],
                "indexes": [dict(idx) for idx in indexes],
            }

    async def get_schema_as_text(self) -> str:
        tables = await self.get_all_tables()
        if not tables:
            return "The database appears to be empty (no user tables found)."

        lines: list[str] = ["DATABASE SCHEMA\n" + "=" * 60]
        for t in tables:
            try:
                info = await self.describe_table(t["name"])
                lines.append(f"\nTABLE: {info['table_name']}")
                lines.append("-" * 40)
                for col in info["columns"]:
                    nullable = "NULL" if col["is_nullable"] == "YES" else "NOT NULL"
                    default = f" DEFAULT {col['column_default']}" if col["column_default"] else ""
                    lines.append(f"  {col['column_name']:30s} {col['data_type']:20s} {nullable}{default}")
                if info["primary_keys"]:
                    lines.append(f"  PRIMARY KEY: {', '.join(info['primary_keys'])}")
                for fk in info["foreign_keys"]:
                    lines.append(
                        f"  FK: {fk['column_name']} → {fk['foreign_table']}.{fk['foreign_column']}"
                    )
            except Exception as exc:
                lines.append(f"\nTABLE: {t['name']} (error reading schema: {exc})")

        return "\n".join(lines)

    async def check_health(self) -> dict[str, Any]:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                version = await conn.fetchval("SELECT version()")
                db_name = await conn.fetchval("SELECT current_database()")
            return {"status": "ok", "version": version, "database": db_name}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}
