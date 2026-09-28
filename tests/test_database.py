"""Tests for SQL validation (the safety layer)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_blocks_insert():
    from db_mcp.backends.base import DatabaseBackend
    with pytest.raises(ValueError, match="Only SELECT"):
        DatabaseBackend.validate_select("INSERT INTO users VALUES (1, 'test')")


@pytest.mark.asyncio
async def test_blocks_delete():
    from db_mcp.backends.base import DatabaseBackend
    with pytest.raises(ValueError, match="Only SELECT"):
        DatabaseBackend.validate_select("DELETE FROM users WHERE id = 1")


@pytest.mark.asyncio
async def test_blocks_drop():
    from db_mcp.backends.base import DatabaseBackend
    with pytest.raises(ValueError, match="Only SELECT"):
        DatabaseBackend.validate_select("DROP TABLE users")


def test_allows_select():
    from db_mcp.backends.base import DatabaseBackend
    DatabaseBackend.validate_select("SELECT id, name FROM users")


def test_blocks_truncate():
    from db_mcp.backends.base import DatabaseBackend
    with pytest.raises(ValueError, match="Only SELECT"):
        DatabaseBackend.validate_select("TRUNCATE TABLE users")


def test_blocks_alter():
    from db_mcp.backends.base import DatabaseBackend
    with pytest.raises(ValueError, match="Only SELECT"):
        DatabaseBackend.validate_select("ALTER TABLE users ADD COLUMN age INT")
