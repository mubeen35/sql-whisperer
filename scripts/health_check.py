"""Quick health check — run to verify DB + Ollama are reachable."""
import asyncio
import sys
import io

# Force UTF-8 on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "src")

from db_mcp.database import check_db_health
from db_mcp.ollama_client import check_ollama_health
from db_mcp.config import get_settings


async def main():
    settings = get_settings()

    print("=" * 50)
    print("  DATABASE MCP -- HEALTH CHECK")
    print("=" * 50)

    print("\n[DB]  PostgreSQL")
    db = await check_db_health()
    if db["status"] == "ok":
        print("  [OK]  Connected")
        print(f"  Database : {db['database']}")
        print(f"  Version  : {db['version'][:70]}")
    else:
        print(f"  [FAIL]  {db['error']}")

    print("\n[AI]  Ollama")
    print(f"  URL      : {settings.ollama_base_url}")
    print(f"  Model    : {settings.ollama_model}")
    ol = await check_ollama_health()
    if ol["status"] == "ok":
        print("  [OK]  Connected")
        models = ol.get("models", [])
        print(f"  Models   : {', '.join(models[:5])}")
        if settings.ollama_model not in " ".join(models):
            print(f"\n  [WARN] '{settings.ollama_model}' not found locally!")
            print(f"  Run: ollama pull {settings.ollama_model}")
        else:
            print(f"  [OK]  Model '{settings.ollama_model}' is available")
    else:
        print(f"  [FAIL]  {ol['error']}")

    print("\n" + "=" * 50)
    if db["status"] == "ok" and ol["status"] == "ok":
        print("  All systems ready!")
        print("  Run: uv run python -m db_mcp.cli")
    else:
        print("  Fix the errors above before running the CLI")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
