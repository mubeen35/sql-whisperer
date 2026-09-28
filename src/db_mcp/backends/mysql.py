"""MySQL / MariaDB backend using aiomysql."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from db_mcp.backends.base import DatabaseBackend
from db_mcp.config import get_settings

log = logging.getLogger(__name__)


class MySQLBackend(DatabaseBackend):

    dialect_name = "MySQL"

    def __init__(self) -> None:
        self._pool = None
        self._pool_lock = asyncio.Lock()

    async def connect(self) -> None:
        import aiomysql

        async with self._pool_lock:
            if self._pool is None:
                s = get_settings()
                log.info("Creating aiomysql pool",
                         extra={"host": s.db_host, "port": s.db_port, "database": s.db_name})
                self._pool = await aiomysql.create_pool(
                    host=s.db_host,
                    port=s.db_port,
                    db=s.db_name,
                    user=s.db_user,
                    password=s.db_password,
                    minsize=s.db_min_pool_size,
                    maxsize=s.db_max_pool_size,
                    autocommit=True,
                    cursorclass=aiomysql.DictCursor,
                )

    async def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
            log.info("MySQL pool closed")

    async def _get_pool(self):
        if self._pool is None:
            await self.connect()
        return self._pool

    async def execute_readonly_query(
        self, sql: str, params: list[Any] | None = None
    ) -> list[dict[str, Any]]:
        import aiomysql

        self.validate_select(sql)

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                if params:
                    await cur.execute(sql, params)
                else:
                    await cur.execute(sql)
                rows = await cur.fetchall()
                return [dict(row) for row in rows]

    async def get_all_tables(self) -> list[dict[str, Any]]:
        import aiomysql

        s = get_settings()
        sql = """
            SELECT
                TABLE_SCHEMA  AS `schema`,
                TABLE_NAME    AS name,
                TABLE_TYPE    AS type,
                TABLE_ROWS    AS approx_rows
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_SCHEMA, TABLE_NAME
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql, (s.db_name,))
                rows = await cur.fetchall()
                result = []
                for row in rows:
                    d = dict(row)
                    d["approx_rows"] = d.get("approx_rows") or -1
                    result.append(d)
                return result

    async def describe_table(self, table_name: str) -> dict[str, Any]:
        import aiomysql

        s = get_settings()
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # columns
                await cur.execute(
                    """
                    SELECT
                        COLUMN_NAME     AS column_name,
                        DATA_TYPE       AS data_type,
                        CHARACTER_MAXIMUM_LENGTH AS character_maximum_length,
                        NUMERIC_PRECISION AS numeric_precision,
                        IS_NULLABLE     AS is_nullable,
                        COLUMN_DEFAULT  AS column_default,
                        ORDINAL_POSITION AS ordinal_position
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                    ORDER BY ORDINAL_POSITION
                    """,
                    (s.db_name, table_name),
                )
                columns = await cur.fetchall()

                if not columns:
                    raise ValueError(f"Table '{table_name}' not found in the database.")

                # primary keys
                await cur.execute(
                    """
                    SELECT COLUMN_NAME AS column_name
                    FROM information_schema.KEY_COLUMN_USAGE
                    WHERE TABLE_SCHEMA = %s
                      AND TABLE_NAME = %s
                      AND CONSTRAINT_NAME = 'PRIMARY'
                    ORDER BY ORDINAL_POSITION
                    """,
                    (s.db_name, table_name),
                )
                pks = await cur.fetchall()

                # foreign keys
                await cur.execute(
                    """
                    SELECT
                        kcu.COLUMN_NAME       AS column_name,
                        kcu.REFERENCED_TABLE_NAME  AS foreign_table,
                        kcu.REFERENCED_COLUMN_NAME AS foreign_column
                    FROM information_schema.KEY_COLUMN_USAGE kcu
                    WHERE kcu.TABLE_SCHEMA = %s
                      AND kcu.TABLE_NAME = %s
                      AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
                    """,
                    (s.db_name, table_name),
                )
                fks = await cur.fetchall()

                # indexes
                await cur.execute(
                    """
                    SELECT
                        INDEX_NAME AS indexname,
                        GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS indexdef
                    FROM information_schema.STATISTICS
                    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                    GROUP BY INDEX_NAME
                    ORDER BY INDEX_NAME
                    """,
                    (s.db_name, table_name),
                )
                indexes = await cur.fetchall()

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
        import aiomysql

        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute("SELECT VERSION() AS version")
                    row = await cur.fetchone()
                    version = row["version"] if row else "unknown"
                    await cur.execute("SELECT DATABASE() AS db_name")
                    row = await cur.fetchone()
                    db_name = row["db_name"] if row else "unknown"
            return {"status": "ok", "version": f"MySQL {version}", "database": db_name}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}
