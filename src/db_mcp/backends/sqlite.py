"""SQLite backend using aiosqlite."""

from __future__ import annotations

import logging
from typing import Any

from db_mcp.backends.base import DatabaseBackend
from db_mcp.config import get_settings

log = logging.getLogger(__name__)


class SQLiteBackend(DatabaseBackend):

    dialect_name = "SQLite"

    def __init__(self) -> None:
        self._conn = None

    async def connect(self) -> None:
        import aiosqlite

        if self._conn is None:
            s = get_settings()
            log.info("Opening SQLite database", extra={"path": s.db_path})
            self._conn = await aiosqlite.connect(s.db_path)
            self._conn.row_factory = aiosqlite.Row

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            log.info("SQLite connection closed")

    async def _get_conn(self):
        if self._conn is None:
            await self.connect()
        return self._conn

    async def execute_readonly_query(
        self, sql: str, params: list[Any] | None = None
    ) -> list[dict[str, Any]]:
        self.validate_select(sql)

        conn = await self._get_conn()
        cursor = await conn.execute(sql, params or [])
        rows = await cursor.fetchall()
        if not rows:
            return []
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    async def get_all_tables(self) -> list[dict[str, Any]]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            """
            SELECT name, type
            FROM sqlite_master
            WHERE type IN ('table', 'view')
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            tbl_type = "BASE TABLE" if row[1] == "table" else "VIEW"
            approx_rows = -1
            try:
                c2 = await conn.execute(f'SELECT COUNT(*) FROM "{row[0]}"')
                count_row = await c2.fetchone()
                approx_rows = count_row[0] if count_row else -1
            except Exception:
                pass
            result.append({
                "schema": "main",
                "name": row[0],
                "type": tbl_type,
                "approx_rows": approx_rows,
            })
        return result

    async def describe_table(self, table_name: str) -> dict[str, Any]:
        conn = await self._get_conn()

        cursor = await conn.execute(f'PRAGMA table_info("{table_name}")')
        pragma_rows = await cursor.fetchall()
        if not pragma_rows:
            raise ValueError(f"Table '{table_name}' not found in the database.")

        columns = []
        primary_keys = []
        for i, row in enumerate(pragma_rows):
            # cid, name, type, notnull, dflt_value, pk
            col = {
                "column_name": row[1],
                "data_type": row[2] or "TEXT",
                "character_maximum_length": None,
                "numeric_precision": None,
                "is_nullable": "NO" if row[3] else "YES",
                "column_default": row[4],
                "ordinal_position": i + 1,
            }
            columns.append(col)
            if row[5]:
                primary_keys.append(row[1])

        cursor = await conn.execute(f'PRAGMA foreign_key_list("{table_name}")')
        fk_rows = await cursor.fetchall()
        foreign_keys = []
        for fk in fk_rows:
            # id, seq, table, from, to, on_update, on_delete, match
            foreign_keys.append({
                "column_name": fk[3],
                "foreign_table": fk[2],
                "foreign_column": fk[4],
            })

        cursor = await conn.execute(f'PRAGMA index_list("{table_name}")')
        idx_rows = await cursor.fetchall()
        indexes = []
        for idx in idx_rows:
            indexes.append({
                "indexname": idx[1],
                "indexdef": f"{'UNIQUE ' if idx[2] else ''}INDEX {idx[1]}",
            })

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
            conn = await self._get_conn()
            cursor = await conn.execute("SELECT sqlite_version()")
            row = await cursor.fetchone()
            version = row[0] if row else "unknown"
            s = get_settings()
            return {
                "status": "ok",
                "version": f"SQLite {version}",
                "database": s.db_path,
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}
