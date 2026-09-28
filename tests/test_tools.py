"""Tests for SQL extraction and row formatting helpers."""
from __future__ import annotations

import pytest
from db_mcp.tools import _extract_sql, _format_rows


def test_extract_from_fenced_block():
    text = "Here is the query:\n```sql\nSELECT * FROM users;\n```\nDone."
    assert _extract_sql(text) == "SELECT * FROM users;"


def test_extract_bare_select():
    text = "Sure! SELECT id, name FROM users LIMIT 10;"
    assert "SELECT" in _extract_sql(text).upper()


def test_extract_fenced_no_lang_tag():
    text = "```\nSELECT count(*) FROM orders;\n```"
    assert "SELECT" in _extract_sql(text).upper()


def test_extract_returns_raw_when_no_select():
    text = "I cannot generate SQL for this question."
    assert _extract_sql(text) == text


def test_format_empty():
    assert _format_rows([]) == "Query returned 0 rows."


def test_format_single_row():
    rows = [{"id": 1, "name": "Alice"}]
    result = _format_rows(rows)
    assert "Alice" in result
    assert "id" in result
    assert "name" in result


def test_format_truncation():
    rows = [{"n": i} for i in range(200)]
    result = _format_rows(rows, max_rows=50)
    assert "50 of 200" in result


def test_format_no_truncation_within_limit():
    rows = [{"n": i} for i in range(10)]
    result = _format_rows(rows, max_rows=50)
    assert "showing" not in result
