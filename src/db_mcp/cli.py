"""
Interactive CLI for the Database MCP Assistant.

Run directly to query your database from the terminal — no Claude Desktop needed.

    python -m db_mcp.cli
    uv run python -m db_mcp.cli

Commands:
    ask   <question>   — Natural language question (Ollama generates SQL)
    sql   <query>      — Run a raw SELECT query
    tables             — List all tables
    desc  <table>      — Describe a table's structure
    schema             — Show full database schema
    health             — Check DB + Ollama connectivity
    models             — List available Ollama models
    help / exit
"""

from __future__ import annotations

import asyncio
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich import print as rprint

from db_mcp import database, ollama_client
from db_mcp.config import get_settings
from db_mcp.tools import _format_rows, _extract_sql

console = Console()


def _print_banner() -> None:
    settings = get_settings()
    dialect = database.get_dialect_name()

    db_type = settings.db_type.lower().strip()
    if db_type == "sqlite":
        db_info = f"[green]{settings.db_path}[/green]"
    else:
        db_info = f"[green]{settings.db_user}@{settings.db_host}:{settings.db_port}/{settings.db_name}[/green]"

    console.print(
        Panel.fit(
            f"[bold cyan]🗄  Database MCP Assistant[/bold cyan]\n"
            f"[dim]Engine:[/dim] [yellow]{dialect}[/yellow]\n"
            f"[dim]DB:[/dim] {db_info}\n"
            f"[dim]Ollama:[/dim] [green]{settings.ollama_base_url}[/green]  "
            f"[dim]Model:[/dim] [yellow]{settings.ollama_model}[/yellow]\n\n"
            f"[dim]Type [/dim][bold]help[/bold][dim] for available commands, "
            f"[/dim][bold]exit[/bold][dim] to quit.[/dim]",
            border_style="cyan",
        )
    )


HELP_TEXT = """\
## Available Commands

| Command | Description |
|---------|-------------|
| `ask <question>` | Ask a natural language question — Ollama generates and runs the SQL |
| `sql <query>` | Execute a raw READ-ONLY SELECT query |
| `tables` | List all tables and views |
| `desc <table>` | Describe a table's columns and structure |
| `schema` | Print the full database schema |
| `health` | Check database + Ollama connectivity |
| `models` | List locally available Ollama models |
| `help` | Show this help message |
| `exit` | Exit the CLI |

## Tips
- Start with `health` to verify everything is connected.
- Use `tables` to explore what's in your database.
- `ask` is the most powerful — just describe what you want in plain English.
"""


async def cmd_health() -> None:
    dialect = database.get_dialect_name()
    console.print(Rule("[cyan]Health Check[/cyan]"))
    with console.status("[bold cyan]Checking connectivity…"):
        db = await database.check_db_health()
        ol = await ollama_client.check_ollama_health()

    db_color = "green" if db["status"] == "ok" else "red"
    console.print(f"\n[bold]{dialect}[/bold]  [{db_color}]{db['status'].upper()}[/{db_color}]")
    if db["status"] == "ok":
        console.print(f"  Database : {db.get('database')}")
        console.print(f"  Version  : {db.get('version')}")
    else:
        console.print(f"  [red]Error: {db.get('error')}[/red]")

    ol_color = "green" if ol["status"] == "ok" else "red"
    settings = get_settings()
    console.print(f"\n[bold]Ollama[/bold]      [{ol_color}]{ol['status'].upper()}[/{ol_color}]")
    console.print(f"  URL      : {settings.ollama_base_url}")
    console.print(f"  Model    : {settings.ollama_model}")
    if ol["status"] == "ok":
        models = ol.get("models", [])
        console.print(f"  Models   : {', '.join(models) if models else 'none pulled'}")
        if models and settings.ollama_model not in " ".join(models):
            console.print(
                f"\n  [yellow]⚠  Model '{settings.ollama_model}' not found locally.[/yellow]\n"
                f"  [dim]Run: ollama pull {settings.ollama_model}[/dim]"
            )
    else:
        console.print(f"  [red]Error: {ol.get('error')}[/red]")
    console.print()


async def cmd_list_tables() -> None:
    console.print(Rule("[cyan]Tables[/cyan]"))
    with console.status("[bold cyan]Fetching tables…"):
        tables = await database.get_all_tables()

    if not tables:
        console.print("[yellow]No user tables found. The database appears to be empty.[/yellow]")
        return

    tbl = Table(show_header=True, header_style="bold magenta")
    tbl.add_column("Schema", style="dim")
    tbl.add_column("Name", style="bold cyan")
    tbl.add_column("Type")
    tbl.add_column("Approx Rows", justify="right")

    for t in tables:
        rows_str = str(t["approx_rows"]) if t["approx_rows"] >= 0 else "?"
        tbl.add_row(t["schema"], t["name"], t["type"], rows_str)

    console.print(tbl)
    console.print(f"[dim]Total: {len(tables)} object(s)[/dim]\n")


async def cmd_describe(table_name: str) -> None:
    console.print(Rule(f"[cyan]Table: {table_name}[/cyan]"))
    with console.status(f"[bold cyan]Describing {table_name}…"):
        try:
            info = await database.describe_table(table_name)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return

    tbl = Table(show_header=True, header_style="bold magenta")
    tbl.add_column("Column", style="bold cyan", min_width=20)
    tbl.add_column("Type", min_width=18)
    tbl.add_column("Nullable", justify="center")
    tbl.add_column("Default")

    pks = set(info["primary_keys"])
    for col in info["columns"]:
        name = col["column_name"]
        pk_marker = " 🔑" if name in pks else ""
        nullable = "✓" if col["is_nullable"] == "YES" else "✗"
        tbl.add_row(
            f"{name}{pk_marker}",
            col["data_type"],
            nullable,
            col["column_default"] or "",
        )

    console.print(tbl)

    if info["foreign_keys"]:
        console.print("[bold]Foreign Keys:[/bold]")
        for fk in info["foreign_keys"]:
            console.print(f"  [cyan]{fk['column_name']}[/cyan] → {fk['foreign_table']}.{fk['foreign_column']}")

    if info["indexes"]:
        console.print("\n[bold]Indexes:[/bold]")
        for idx in info["indexes"]:
            console.print(f"  [dim]{idx['indexname']}[/dim]")
    console.print()


async def cmd_schema() -> None:
    console.print(Rule("[cyan]Full Schema[/cyan]"))
    with console.status("[bold cyan]Loading schema…"):
        schema = await database.get_schema_as_text()
    console.print(schema)
    console.print()


async def cmd_execute_sql(sql: str) -> None:
    console.print(Rule("[cyan]SQL Query[/cyan]"))
    console.print(Syntax(sql, "sql", theme="monokai", word_wrap=True))

    with console.status("[bold cyan]Executing…"):
        try:
            rows = await database.execute_readonly_query(sql)
        except ValueError as exc:
            console.print(f"[red]Rejected: {exc}[/red]")
            return
        except Exception as exc:
            console.print(f"[red]SQL Error: {exc}[/red]")
            return

    if not rows:
        console.print("[yellow]Query returned 0 rows.[/yellow]")
        return

    tbl = Table(show_header=True, header_style="bold magenta", row_styles=["", "dim"])
    for col in rows[0].keys():
        tbl.add_column(col)

    display = rows[:100]
    for row in display:
        tbl.add_row(*[str(v) if v is not None else "[dim]NULL[/dim]" for v in row.values()])

    console.print(tbl)
    if len(rows) > 100:
        console.print(f"[dim]… showing 100 of {len(rows)} rows[/dim]")
    else:
        console.print(f"[dim]{len(rows)} row(s) returned[/dim]")
    console.print()


async def cmd_ask(question: str) -> None:
    settings = get_settings()
    dialect = database.get_dialect_name()
    console.print(Rule(f"[cyan]Ask: {question[:60]}[/cyan]"))

    with console.status("[bold cyan]Loading schema…"):
        try:
            schema = await database.get_schema_as_text()
        except Exception as exc:
            console.print(f"[red]Could not load schema: {exc}[/red]")
            return

    sql_prompt = (
        f"You are a {dialect} expert. Given the schema below, write a SQL SELECT query "
        f"to answer the user's question. Use {dialect}-compatible syntax. "
        f"Return ONLY the SQL query inside a ```sql code block. "
        f"Do NOT include any explanation.\n\n"
        f"SCHEMA:\n{schema}\n\n"
        f"QUESTION: {question}\n\nSQL:"
    )

    with console.status(f"[bold cyan]Asking {settings.ollama_model} to generate SQL…"):
        try:
            sql_response = await ollama_client.chat(
                messages=[{"role": "user", "content": sql_prompt}]
            )
        except Exception as exc:
            console.print(f"[red]Ollama error (SQL generation): {exc}[/red]")
            return

    generated_sql = _extract_sql(sql_response)
    console.print("\n[bold]Generated SQL:[/bold]")
    console.print(Syntax(generated_sql, "sql", theme="monokai", word_wrap=True))

    with console.status("[bold cyan]Executing query…"):
        try:
            rows = await database.execute_readonly_query(generated_sql)
        except Exception as exc:
            console.print(f"[red]SQL execution failed: {exc}[/red]")
            console.print("[dim]Try rephrasing your question or use the `sql` command manually.[/dim]")
            return

    console.print(f"[dim]Query returned {len(rows)} row(s)[/dim]")

    rows_text = _format_rows(rows, max_rows=50)
    summary_prompt = (
        f"The user asked: \"{question}\"\n\n"
        f"SQL executed:\n```sql\n{generated_sql}\n```\n\n"
        f"Results ({len(rows)} rows):\n{rows_text}\n\n"
        f"Provide a clear, concise answer to the user's question based on these results. "
        f"Be specific with numbers. Do not repeat the SQL or raw table unless it adds value."
    )

    with console.status(f"[bold cyan]Summarizing with {settings.ollama_model}…"):
        try:
            summary = await ollama_client.chat(
                messages=[{"role": "user", "content": summary_prompt}]
            )
        except Exception as exc:
            console.print(f"[yellow]Could not summarize (Ollama error: {exc}). Raw results:[/yellow]")
            console.print(rows_text)
            return

    console.print()
    console.print(Panel(Markdown(summary), title="[bold green]Answer[/bold green]", border_style="green"))
    console.print()


async def cmd_models() -> None:
    console.print(Rule("[cyan]Available Ollama Models[/cyan]"))
    with console.status("[bold cyan]Fetching models…"):
        models = await ollama_client.list_models()

    if not models:
        console.print("[yellow]No models found. Is Ollama running?[/yellow]")
        return

    settings = get_settings()
    for model in models:
        marker = " [green]← active[/green]" if settings.ollama_model in model else ""
        console.print(f"  • [cyan]{model}[/cyan]{marker}")
    console.print()


async def repl() -> None:
    """Main REPL loop."""
    _print_banner()
    await cmd_health()

    while True:
        try:
            raw = Prompt.ask("[bold cyan]db>[/bold cyan]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not raw:
            continue

        parts = raw.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        try:
            if cmd in ("exit", "quit", "q"):
                console.print("[dim]Goodbye![/dim]")
                break
            elif cmd == "help":
                console.print(Markdown(HELP_TEXT))
            elif cmd == "health":
                await cmd_health()
            elif cmd == "tables":
                await cmd_list_tables()
            elif cmd == "desc" and arg:
                await cmd_describe(arg)
            elif cmd == "desc":
                console.print("[red]Usage: desc <table_name>[/red]")
            elif cmd == "schema":
                await cmd_schema()
            elif cmd == "sql" and arg:
                await cmd_execute_sql(arg)
            elif cmd == "sql":
                console.print("[red]Usage: sql <SELECT query>[/red]")
            elif cmd == "ask" and arg:
                await cmd_ask(arg)
            elif cmd == "ask":
                console.print("[red]Usage: ask <your question>[/red]")
            elif cmd == "models":
                await cmd_models()
            else:
                # not a known command — if it's long enough, treat as a question
                if len(raw) > 5:
                    console.print(
                        f"[dim]Unknown command '{cmd}'. Treating as question… "
                        f"(use 'ask <question>' explicitly)[/dim]"
                    )
                    await cmd_ask(raw)
                else:
                    console.print(f"[red]Unknown command: '{cmd}'. Type 'help' for available commands.[/red]")
        except KeyboardInterrupt:
            console.print("\n[dim](Interrupted)[/dim]")
        except Exception as exc:
            console.print(f"[red]Unexpected error: {exc}[/red]")


def app() -> None:
    """Entry point for the 'db-cli' command."""
    asyncio.run(repl())


if __name__ == "__main__":
    app()
