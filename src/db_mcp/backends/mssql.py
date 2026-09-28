"""SQL Server backend using aioodbc.

Requires an ODBC driver installed on the system (e.g. "ODBC Driver 17 for SQL Server").
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from db_mcp.backends.base import DatabaseBackend
from db_mcp.config import get_settings

log = logging.getLogger(__name__)


class MSSQLBackend(DatabaseBackend):

    dialect_name = "SQL Server"

    def __init__(self) -> None:
        self._pool = None
        self._pool_lock = asyncio.Lock()

    async def connect(self) -> None:
        import aioodbc

        async with self._pool_lock:
            if self._pool is None:
                s = get_settings()
                dsn = (
                    f"DRIVER={{{s.db_odbc_driver}}};"
                    f"SERVER={s.db_host},{s.db_port};"
                    f"DATABASE={s.db_name};"
                    f"UID={s.db_user};"
                    f"PWD={s.db_password};"
                    f"TrustServerCertificate=yes;"
                )
                log.info("Creating aioodbc pool for SQL Server",
                         extra={"host": s.db_host, "port": s.db_port, "database": s.db_name})
                self._pool = await aioodbc.create_pool(
                    dsn=dsn,
                    minsize=s.db_min_pool_size,
                    maxsize=s.db_max_pool_size,
                )

    async def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
            log.info("SQL Server pool closed")

    async def _get_pool(self):
        if self._pool is None:
            await self.connect()
        return self._pool

    async def execute_readonly_query(
        self, sql: str, params: list[Any] | None = None
    ) -> list[dict[str, Any]]:
        self.validate_select(sql)

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                if params:
                    await cur.execute(sql, params)
                else:
                    await cur.execute(sql)
                columns = [desc[0] for desc in cur.description]
                rows = await cur.fetchall()
                return [dict(zip(columns, row)) for row in rows]

    async def get_all_tables(self) -> list[dict[str, Any]]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT
                        s.name       AS [schema],
                        t.name       AS [name],
                        t.type_desc  AS [type],
                        p.rows       AS approx_rows
                    FROM sys.tables t
                    JOIN sys.schemas s ON t.schema_id = s.schema_id
                    LEFT JOIN sys.partitions p
                        ON t.object_id = p.object_id AND p.index_id IN (0, 1)
                    UNION ALL
                    SELECT
                        s.name, v.name, 'VIEW', 0
                    FROM sys.views v
                    JOIN sys.schemas s ON v.schema_id = s.schema_id
                    ORDER BY 1, 2
                    """
                )
                columns = [desc[0] for desc in cur.description]
                rows = await cur.fetchall()
                return [dict(zip(columns, row)) for row in rows]

    async def describe_table(self, table_name: str) -> dict[str, Any]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # columns
                await cur.execute(
                    """
                    SELECT
                        c.name            AS column_name,
                        tp.name           AS data_type,
                        c.max_length      AS character_maximum_length,
                        c.precision       AS numeric_precision,
                        CASE c.is_nullable WHEN 1 THEN 'YES' ELSE 'NO' END AS is_nullable,
                        dc.definition     AS column_default,
                        c.column_id       AS ordinal_position
                    FROM sys.columns c
                    JOIN sys.types tp ON c.user_type_id = tp.user_type_id
                    JOIN sys.tables t ON c.object_id = t.object_id
                    LEFT JOIN sys.default_constraints dc
                        ON c.default_object_id = dc.object_id
                    WHERE t.name = ?
                    ORDER BY c.column_id
                    """,
                    (table_name,),
                )
                columns_desc = [desc[0] for desc in cur.description]
                col_rows = await cur.fetchall()
                columns = [dict(zip(columns_desc, r)) for r in col_rows]

                if not columns:
                    raise ValueError(f"Table '{table_name}' not found in the database.")

                # primary keys
                await cur.execute(
                    """
                    SELECT col.name AS column_name
                    FROM sys.index_columns ic
                    JOIN sys.columns col ON ic.object_id = col.object_id
                        AND ic.column_id = col.column_id
                    JOIN sys.indexes ix ON ic.object_id = ix.object_id
                        AND ic.index_id = ix.index_id
                    JOIN sys.tables t ON ix.object_id = t.object_id
                    WHERE ix.is_primary_key = 1 AND t.name = ?
                    ORDER BY ic.key_ordinal
                    """,
                    (table_name,),
                )
                pk_rows = await cur.fetchall()
                primary_keys = [r[0] for r in pk_rows]

                # foreign keys
                await cur.execute(
                    """
                    SELECT
                        COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS column_name,
                        OBJECT_NAME(fkc.referenced_object_id) AS foreign_table,
                        COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS foreign_column
                    FROM sys.foreign_key_columns fkc
                    JOIN sys.tables t ON fkc.parent_object_id = t.object_id
                    WHERE t.name = ?
                    """,
                    (table_name,),
                )
                fk_desc = [desc[0] for desc in cur.description]
                fk_rows = await cur.fetchall()
                foreign_keys = [dict(zip(fk_desc, r)) for r in fk_rows]

                # indexes
                await cur.execute(
                    """
                    SELECT
                        ix.name AS indexname,
                        ix.type_desc AS indexdef
                    FROM sys.indexes ix
                    JOIN sys.tables t ON ix.object_id = t.object_id
                    WHERE t.name = ? AND ix.name IS NOT NULL
                    ORDER BY ix.name
                    """,
                    (table_name,),
                )
                idx_desc = [desc[0] for desc in cur.description]
                idx_rows = await cur.fetchall()
                indexes = [dict(zip(idx_desc, r)) for r in idx_rows]

                return {
                    "table_name": table_name,
                    "columns": columns,
                    "primary_keys": primary_keys,
                    "foreign_keys": foreign_keys,
                    "indexes": indexes,
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
                async with conn.cursor() as cur:
                    await cur.execute("SELECT @@VERSION")
                    row = await cur.fetchone()
                    version = row[0] if row else "unknown"
                    await cur.execute("SELECT DB_NAME()")
                    row = await cur.fetchone()
                    db_name = row[0] if row else "unknown"
            return {"status": "ok", "version": version, "database": db_name}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}
