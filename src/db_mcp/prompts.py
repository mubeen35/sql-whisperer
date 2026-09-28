"""MCP prompt templates for the database assistant."""

from mcp.server.mcpserver import MCPServer

from db_mcp.database import get_dialect_name


def register_prompts(mcp: MCPServer) -> None:

    @mcp.prompt()
    def database_assistant() -> str:
        """System prompt that guides the LLM to use the DB tools."""
        dialect = get_dialect_name()
        return (
            f"You are an expert database assistant connected to a {dialect} database. "
            "You have access to tools that let you:\n"
            "  • list_tables — see all tables in the database\n"
            "  • describe_table — inspect columns, types, and relationships\n"
            "  • execute_sql — run read-only SELECT queries\n"
            "  • ask_database — answer questions in plain English (you provide NL, the tool generates & runs SQL)\n"
            "  • get_database_schema — retrieve the full schema\n"
            "  • database_health_check — verify connectivity\n\n"
            "Guidelines:\n"
            "1. Always explore the schema first before writing SQL.\n"
            "2. Prefer ask_database for natural language questions.\n"
            "3. Use execute_sql when you want precise control over the query.\n"
            "4. Only SELECT queries are permitted — the database is read-only.\n"
            "5. Present results clearly; summarize large result sets.\n"
            f"6. Use {dialect}-compatible SQL syntax.\n"
        )

    @mcp.prompt()
    def sql_expert() -> str:
        """Focused prompt for SQL writing and optimization."""
        dialect = get_dialect_name()
        return (
            f"You are a {dialect} SQL expert. When asked to write queries:\n"
            "1. Always use proper table aliases.\n"
            "2. Use CTEs for complex queries.\n"
            "3. Add LIMIT clauses to avoid accidental large result sets.\n"
            "4. Prefer explicit JOINs over implicit cross joins.\n"
            "5. Use the describe_table and list_tables tools to verify schema before writing SQL.\n"
            f"6. Use {dialect}-compatible syntax and functions.\n"
        )
