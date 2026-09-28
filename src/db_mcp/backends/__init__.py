"""
Backend registry — picks the right DB driver based on DB_TYPE.

    from db_mcp.backends import get_backend
    backend = get_backend()  # reads DB_TYPE from settings
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db_mcp.backends.base import DatabaseBackend

log = logging.getLogger(__name__)

# maps DB_TYPE values -> (module, class)
_REGISTRY: dict[str, tuple[str, str]] = {
    "postgresql": ("db_mcp.backends.postgresql", "PostgreSQLBackend"),
    "postgres":   ("db_mcp.backends.postgresql", "PostgreSQLBackend"),
    "mysql":      ("db_mcp.backends.mysql",      "MySQLBackend"),
    "mariadb":    ("db_mcp.backends.mysql",      "MySQLBackend"),
    "sqlite":     ("db_mcp.backends.sqlite",     "SQLiteBackend"),
    "mssql":      ("db_mcp.backends.mssql",      "MSSQLBackend"),
    "sqlserver":  ("db_mcp.backends.mssql",      "MSSQLBackend"),
}

_instance: DatabaseBackend | None = None


def get_backend(db_type: str | None = None) -> "DatabaseBackend":
    """
    Return a singleton backend. If db_type isn't given, reads from settings.
    """
    global _instance

    if _instance is not None:
        return _instance

    if db_type is None:
        from db_mcp.config import get_settings
        db_type = get_settings().db_type

    db_type = db_type.lower().strip()

    if db_type not in _REGISTRY:
        supported = ", ".join(sorted(set(
            k for k in _REGISTRY if k in ("postgresql", "mysql", "sqlite", "mssql")
        )))
        raise ValueError(f"Unsupported database type '{db_type}'. Supported: {supported}")

    module_path, class_name = _REGISTRY[db_type]

    import importlib
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)

    _instance = cls()
    log.info(f"Initialized {_instance.dialect_name} backend")
    return _instance


def reset_backend() -> None:
    """Clear the singleton. Mainly useful in tests."""
    global _instance
    _instance = None


def supported_db_types() -> list[str]:
    return ["postgresql", "mysql", "sqlite", "mssql"]
