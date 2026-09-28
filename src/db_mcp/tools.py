"""
MCP tools — the core stuff exposed to MCP clients and the CLI.

Safety: execute_sql only allows SELECTs. ask_database validates the
generated SQL before running it.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from mcp.server.mcpserver import MCPServer

from db_mcp import database
from db_mcp.config import get_settings

log = logging.getLogger(__name__)


def _extract_sql(text: str) -> str:
    """Pull a SELECT out of Ollama's response. Handles ```sql fences and bare SQL."""
    # try markdown fence first
    m = re.search(r"```(?:sql)?\s*(SELECT[\s\S]+?)```", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # bare SELECT ... ;
    m = re.search(r"(SELECT[\s\S]+?;)", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # nothing recognizable — return as-is, the DB layer will reject if it's bad
    return text.strip()


def _format_rows(rows: list[dict[str, Any]], max_rows: int = 50) -> str:
    """Format rows into a simple text table."""
    if not rows:
        return "Query returned 0 rows."

    truncated = len(rows) > max_rows
    display = rows[:max_rows]
    if not display:
        return "No data."

    headers = list(display[0].keys())
    col_widths = {h: max(len(h), max(len(str(r.get(h, ""))) for r in display)) for h in headers}
    sep = "-+-".join("-" * col_widths[h] for h in headers)
    header_row = " | ".join(h.ljust(col_widths[h]) for h in headers)

    lines = [header_row, sep]
    for row in display:
        lines.append(" | ".join(str(row.get(h, "")).ljust(col_widths[h]) for h in headers))

    result = "\n".join(lines)
    if truncated:
        result += f"\n\n… (showing {max_rows} of {len(rows)} rows)"
    return result


def register_tools(mcp: MCPServer) -> None:
    """Hook up all the MCP tools."""

    @mcp.tool()
    async def list_tables() -> str:
        """
        List all tables and views in the connected database.

        Returns a formatted table with: schema, name, type, and approximate row count.
        Use this first to understand what data is available before writing queries.
        """
        try:
            tables = await database.get_all_tables()
            if not tables:
                return "No user tables found. The database may be empty."

            lines = [f"{'SCHEMA':<20} {'NAME':<40} {'TYPE':<20} {'APPROX ROWS':>12}"]
            lines.append("-" * 95)
            for t in tables:
                lines.append(
                    f"{t['schema']:<20} {t['name']:<40} {t['type']:<20} {t['approx_rows']:>12}"
                )
            lines.append(f"\nTotal: {len(tables)} object(s)")
            return "\n".join(lines)
        except Exception as exc:
            log.exception("list_tables failed")
            return f"Error listing tables: {exc}"

    @mcp.tool()
    async def describe_table(table_name: str) -> str:
        """
        Describe the structure of a specific table including columns, types,
        primary keys, foreign keys, and indexes.

        Args:
            table_name: The name of the table to describe (e.g. 'users', 'orders').
        """
        try:
            info = await database.describe_table(table_name)

            lines = [f"TABLE: {info['table_name']}", "=" * 60]
            lines.append(f"\n{'COLUMN':<30} {'TYPE':<25} {'NULLABLE':<10} {'DEFAULT'}")
            lines.append("-" * 80)
            for col in info["columns"]:
                nullable = "YES" if col["is_nullable"] == "YES" else "NO"
                default = col["column_default"] or ""
                lines.append(
                    f"{col['column_name']:<30} {col['data_type']:<25} {nullable:<10} {default}"
                )

            if info["primary_keys"]:
                lines.append(f"\nPRIMARY KEY: {', '.join(info['primary_keys'])}")

            if info["foreign_keys"]:
                lines.append("\nFOREIGN KEYS:")
                for fk in info["foreign_keys"]:
                    lines.append(f"  {fk['column_name']} → {fk['foreign_table']}.{fk['foreign_column']}")

            if info["indexes"]:
                lines.append("\nINDEXES:")
                for idx in info["indexes"]:
                    lines.append(f"  {idx['indexname']}: {idx.get('indexdef', '')}")

            return "\n".join(lines)
        except ValueError as exc:
            return f"Table not found: {exc}"
        except Exception as exc:
            log.exception("describe_table failed")
            return f"Error describing table: {exc}"

    @mcp.tool()
    async def execute_sql(sql: str) -> str:
        """
        Execute a read-only SQL SELECT query against the database and return results.

        Only SELECT statements are permitted. The query runs inside a READ ONLY
        transaction for safety. Results are limited to 100 rows for display.

        Args:
            sql: A valid SELECT query appropriate for the connected database.

        Example:
            execute_sql("SELECT id, name FROM users LIMIT 10")
        """
        try:
            rows = await database.execute_readonly_query(sql)
            count = len(rows)
            result = _format_rows(rows, max_rows=100)
            return f"Rows returned: {count}\n\n{result}"
        except ValueError as exc:
            return f"Query rejected: {exc}"
        except Exception as exc:
            log.exception("execute_sql failed")
            return f"SQL error: {exc}"

    @mcp.tool()
    async def ask_database(question: str) -> str:
        """
        Ask a natural language question about the database.

        This tool:
          1. Fetches the current database schema
          2. Sends the schema + your question to Ollama to generate a SQL query
          3. Executes the generated SQL (read-only)
          4. Sends the results back to Ollama for a plain-English summary
          5. Returns the summary along with the SQL that was used

        Args:
            question: A plain-English question about the data.
                      Examples:
                        "How many users signed up last month?"
                        "What are the top 5 products by revenue?"
                        "Show me all tables and their row counts."
        """
        from db_mcp import ollama_client

        settings = get_settings()
        dialect = database.get_dialect_name()

        # grab schema for context
        try:
            schema = await database.get_schema_as_text()
        except Exception as exc:
            return f"Could not retrieve database schema: {exc}"

        # have ollama write the SQL
        sql_prompt = (
            f"You are a {dialect} expert. Given the schema below, write a SQL SELECT query "
            f"to answer the user's question. Use {dialect}-compatible syntax. "
            f"Return ONLY the SQL query inside a ```sql code block. "
            f"Do NOT include any explanation before or after the code block.\n\n"
            f"SCHEMA:\n{schema}\n\n"
            f"QUESTION: {question}\n\n"
            f"SQL:"
        )

        try:
            sql_response = await ollama_client.chat(
                messages=[{"role": "user", "content": sql_prompt}],
                model=settings.ollama_model,
            )
        except Exception as exc:
            return f"Ollama error during SQL generation: {exc}"

        generated_sql = _extract_sql(sql_response)
        log.info("generated SQL", extra={"sql": generated_sql[:200]})

        # run the generated query
        try:
            rows = await database.execute_readonly_query(generated_sql)
        except ValueError as exc:
            return (
                f"The generated SQL was invalid:\n```sql\n{generated_sql}\n```\n\n"
                f"Error: {exc}\n\n"
                f"Try rephrasing your question or use execute_sql with a manual query."
            )
        except Exception as exc:
            return (
                f"SQL execution failed:\n```sql\n{generated_sql}\n```\n\n"
                f"Error: {exc}"
            )

        # ask ollama to summarize the results
        rows_text = _format_rows(rows, max_rows=50)
        summary_prompt = (
            f"The user asked: \"{question}\"\n\n"
            f"The following SQL was executed:\n```sql\n{generated_sql}\n```\n\n"
            f"Results ({len(rows)} rows):\n{rows_text}\n\n"
            f"Please provide a clear, concise answer to the user's question based on these results. "
            f"Be specific with numbers and names. Do not show the SQL or raw data unless asked."
        )

        try:
            summary = await ollama_client.chat(
                messages=[{"role": "user", "content": summary_prompt}],
                model=settings.ollama_model,
            )
        except Exception as exc:
            summary = f"(Could not summarize — Ollama error: {exc})\n\nRaw results:\n{rows_text}"

        return (
            f"**Answer:** {summary}\n\n"
            f"---\n"
            f"**SQL Used:**\n```sql\n{generated_sql}\n```\n"
            f"**Rows Returned:** {len(rows)}"
        )

    @mcp.tool()
    async def get_database_schema() -> str:
        """
        Return the complete database schema as a formatted text block.

        Includes all tables with columns, data types, nullability,
        primary keys, and foreign keys. Useful for understanding the full
        data model before writing complex queries.
        """
        try:
            return await database.get_schema_as_text()
        except Exception as exc:
            log.exception("get_database_schema failed")
            return f"Error fetching schema: {exc}"

    @mcp.tool()
    async def database_health_check() -> str:
        """
        Check the connectivity status of the database and Ollama service.

        Returns status, database version, and list of available Ollama models.
        Use this to verify your environment is set up correctly.
        """
        from db_mcp import ollama_client

        db_status = await database.check_db_health()
        ollama_status = await ollama_client.check_ollama_health()

        settings = get_settings()
        dialect = database.get_dialect_name()

        lines = [
            "HEALTH CHECK",
            "=" * 50,
            "",
            f"DATABASE ({dialect})",
            f"  Status  : {db_status['status'].upper()}",
        ]
        if db_status["status"] == "ok":
            lines.append(f"  Database: {db_status.get('database', 'N/A')}")
            lines.append(f"  Version : {db_status.get('version', 'N/A')}")
        else:
            lines.append(f"  Error   : {db_status.get('error')}")

        lines += [
            "",
            "OLLAMA",
            f"  Status  : {ollama_status['status'].upper()}",
            f"  URL     : {settings.ollama_base_url}",
            f"  Model   : {settings.ollama_model}",
        ]
        if ollama_status["status"] == "ok":
            models = ollama_status.get("models", [])
            lines.append(f"  Models  : {', '.join(models) if models else 'none pulled'}")
            if settings.ollama_model not in " ".join(models):
                lines.append(
                    f"\n  ⚠ WARNING: Configured model '{settings.ollama_model}' "
                    f"may not be pulled. Run: ollama pull {settings.ollama_model}"
                )
        else:
            lines.append(f"  Error   : {ollama_status.get('error')}")

        return "\n".join(lines)
