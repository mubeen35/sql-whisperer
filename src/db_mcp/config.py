"""Config management — loads from env vars / .env via pydantic-settings."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings. Env vars take precedence over .env file defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    db_type: str = "postgresql"  # postgresql | mysql | sqlite | mssql
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "mydb"
    db_user: str = "postgres"
    db_password: str = ""
    db_min_pool_size: int = 1
    db_max_pool_size: int = 10

    # SQLite only
    db_path: str = "database.db"

    # SQL Server ODBC driver
    db_odbc_driver: str = "ODBC Driver 17 for SQL Server"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    ollama_timeout: int = 120  # NL->SQL can be slow on local hardware

    # MCP Server
    mcp_transport: str = "stdio"  # "stdio" | "sse"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000

    # Logging
    log_level: str = "INFO"

    @property
    def db_dsn(self) -> str:
        """Build a connection DSN based on db_type."""
        db_type = self.db_type.lower().strip()
        if db_type in ("postgresql", "postgres"):
            return (
                f"postgresql://{self.db_user}:{self.db_password}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}"
            )
        elif db_type in ("mysql", "mariadb"):
            return (
                f"mysql://{self.db_user}:{self.db_password}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}"
            )
        elif db_type == "sqlite":
            return f"sqlite:///{self.db_path}"
        elif db_type in ("mssql", "sqlserver"):
            return (
                f"mssql://{self.db_user}:{self.db_password}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}"
            )
        return f"{db_type}://{self.db_host}:{self.db_port}/{self.db_name}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
