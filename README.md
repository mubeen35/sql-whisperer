# 🗄 Database MCP Assistant

A **Model Context Protocol (MCP) server** + **interactive CLI** that works with **any database**, powered by a locally-running **Ollama** model.

Ask questions in plain English — the assistant generates SQL in the correct dialect, runs it, and explains the results.

### Supported Databases

| Database | Driver | `DB_TYPE` value | Install extra |
|----------|--------|-----------------|---------------|
| PostgreSQL | asyncpg | `postgresql` | *(included by default)* |
| MySQL / MariaDB | aiomysql | `mysql` | `uv sync --extra mysql` |
| SQLite | aiosqlite | `sqlite` | `uv sync --extra sqlite` |
| SQL Server | aioodbc | `mssql` | `uv sync --extra mssql` |

---

## Requirements

| Tool | Version | Notes |
|------|---------|-------|
| Python | ≥ 3.11 | |
| [uv](https://docs.astral.sh/uv/) | latest | Package manager |
| [Ollama](https://ollama.ai) | latest | Runs the LLM locally |
| A running database | any | PostgreSQL, MySQL, SQLite, or SQL Server |

---

## Quick Start

### 1. Install dependencies

```powershell
# Install uv if you don't have it
pip install uv

# Install core dependencies (PostgreSQL included by default)
uv sync

# For MySQL support:
uv sync --extra mysql

# For SQLite support:
uv sync --extra sqlite

# For SQL Server support:
uv sync --extra mssql

# Install ALL database drivers:
uv sync --extra all
```

### 2. Configure environment

```powershell
# Copy the example and edit to match your setup
copy .env.example .env
notepad .env
```

Key settings in `.env`:

```env
# Pick your database engine
DB_TYPE=postgresql          # postgresql | mysql | sqlite | mssql

# Connection settings (postgresql, mysql, mssql)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=my_database
DB_USER=my_user
DB_PASSWORD=my_password

# SQLite only — path to the .db file
# DB_PATH=./my_database.db

# SQL Server only — ODBC driver name
# DB_ODBC_DRIVER=ODBC Driver 17 for SQL Server

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3         # ← change this to your model
```

#### Example Configs

**PostgreSQL:**
```env
DB_TYPE=postgresql
DB_HOST=localhost
DB_PORT=5432
DB_NAME=myapp
DB_USER=postgres
DB_PASSWORD=secret
```

**MySQL:**
```env
DB_TYPE=mysql
DB_HOST=localhost
DB_PORT=3306
DB_NAME=myapp
DB_USER=root
DB_PASSWORD=secret
```

**SQLite:**
```env
DB_TYPE=sqlite
DB_PATH=./data/app.db
```

**SQL Server:**
```env
DB_TYPE=mssql
DB_HOST=localhost
DB_PORT=1433
DB_NAME=myapp
DB_USER=sa
DB_PASSWORD=YourStrong!Passw0rd
DB_ODBC_DRIVER=ODBC Driver 17 for SQL Server
```

### 3. Start Ollama

```powershell
# Pull and start your Ollama model (if not already running)
ollama pull llama3
ollama serve
```

### 4. Run the interactive CLI ✅

```powershell
uv run python -m db_mcp.cli
```

You'll see a REPL prompt. Type commands:

```
db> health                          # Check connectivity
db> tables                          # List all tables
db> desc users                      # Describe a table
db> ask How many records are there? # Natural language question
db> sql SELECT count(*) FROM users
db> schema                          # Full schema dump
db> models                          # List Ollama models
db> exit
```

---

## CLI Commands Reference

| Command | Description |
|---------|-------------|
| `ask <question>` | 🤖 Natural language → Ollama generates SQL → executes → summarizes |
| `sql <query>` | ⚡ Run a raw SELECT query directly |
| `tables` | 📋 List all tables and views |
| `desc <table>` | 🔍 Inspect columns, types, keys, indexes |
| `schema` | 📄 Full schema as formatted text |
| `health` | 💚 Check DB + Ollama connectivity |
| `models` | 🧠 List locally available Ollama models |
| `help` | Show this list |
| `exit` | Quit |

---

## Run as MCP Server (for Claude Desktop / Cursor)

```powershell
# Start the MCP server in stdio mode (for MCP clients)
uv run python -m db_mcp.server

# Or launch via MCP dev inspector (for debugging)
uv run mcp dev src/db_mcp/server.py
```

### Claude Desktop Integration

Copy the content of `claude_desktop_config.json` into your Claude Desktop config file at:
```
%APPDATA%\Claude\claude_desktop_config.json
```

Update the `DB_TYPE` and connection settings in the `env` block to match your database.

---

## Run Tests

```powershell
# Install dev dependencies and run tests
uv sync --extra dev
uv run pytest tests/ -v
```

---

## Project Structure

```
MCP/
├── src/db_mcp/
│   ├── __init__.py              # Package init
│   ├── config.py                # Settings from .env (pydantic-settings)
│   ├── database.py              # Thin proxy — delegates to active backend
│   ├── backends/
│   │   ├── __init__.py          # Backend factory & registry
│   │   ├── base.py              # Abstract DatabaseBackend interface
│   │   ├── postgresql.py        # PostgreSQL backend (asyncpg)
│   │   ├── mysql.py             # MySQL/MariaDB backend (aiomysql)
│   │   ├── sqlite.py            # SQLite backend (aiosqlite)
│   │   └── mssql.py             # SQL Server backend (aioodbc)
│   ├── ollama_client.py         # Async Ollama HTTP client (httpx)
│   ├── tools.py                 # MCP tools (list_tables, ask_database, etc.)
│   ├── resources.py             # MCP resources (schema:// URIs)
│   ├── prompts.py               # MCP prompt templates (dialect-aware)
│   ├── server.py                # FastMCP server entry point
│   └── cli.py                   # ← Interactive CLI (start here!)
├── tests/
│   ├── test_database.py         # SQL validation & safety tests
│   ├── test_tools.py            # SQL extraction & formatting tests
│   └── test_ollama.py           # Ollama client tests
├── .env                         # Your credentials (gitignored)
├── .env.example                 # Template
├── pyproject.toml               # Dependencies & optional extras
├── conftest.py                  # Pytest path setup
└── claude_desktop_config.json   # MCP client config snippet
```

---

## How It Works

1. **You set `DB_TYPE`** in `.env` → the factory in `backends/__init__.py` loads the right driver.
2. **`database.py`** is a thin proxy — every module (tools, CLI, server) calls it the same way regardless of which backend is active.
3. **SQL prompts are dialect-aware** — when asking Ollama to generate SQL, the prompt says *"You are a MySQL expert"* (or PostgreSQL, SQLite, etc.).
4. **Schema introspection** uses each engine's native catalog views (`information_schema`, `PRAGMA`, `sys.*`).

---

## Safety

- ✅ All queries run in **READ ONLY** transactions — no accidental writes
- ✅ SQL injection prevented by checking statement type before execution
- ✅ Credentials only loaded from `.env` — never hardcoded
- ✅ All logging goes to `stderr` — stdout reserved for MCP protocol
- ✅ Database drivers are **lazily loaded** — only the selected engine's package is imported

---

## Troubleshooting

**"Connection refused" on DB:**
- Make sure your database server is running.
- Verify `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD` in `.env`.

**"Unsupported database type":**
```powershell
# Check your DB_TYPE value — must be one of:
# postgresql, mysql, sqlite, mssql
```

**"ModuleNotFoundError: No module named 'aiomysql'":**
```powershell
# Install the extra for your database type
uv sync --extra mysql       # for MySQL
uv sync --extra sqlite      # for SQLite
uv sync --extra mssql       # for SQL Server
```

**"Connection refused" on Ollama:**
```powershell
ollama serve                 # Start Ollama
ollama list                  # Check pulled models
ollama pull llama3           # Pull your model
```

**Slow responses:**
Local LLMs can take 10–60 seconds on first call. `OLLAMA_TIMEOUT` defaults to 120s.
