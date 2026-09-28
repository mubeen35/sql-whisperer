"""Tests for the Ollama client."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx


@pytest.mark.asyncio
async def test_health_ok():
    from db_mcp import ollama_client

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "models": [{"name": "llama3:latest"}, {"name": "mistral:latest"}]
    })

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.is_closed = False

    with patch.object(ollama_client, "_get_client", return_value=mock_client):
        result = await ollama_client.check_ollama_health()

    assert result["status"] == "ok"
    assert "llama3:latest" in result["models"]


@pytest.mark.asyncio
async def test_health_connection_error():
    from db_mcp import ollama_client

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
    mock_client.is_closed = False

    with patch.object(ollama_client, "_get_client", return_value=mock_client):
        result = await ollama_client.check_ollama_health()

    assert result["status"] == "error"
    assert "error" in result


@pytest.mark.asyncio
async def test_list_models():
    from db_mcp import ollama_client

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "models": [{"name": "llama3:latest"}, {"name": "phi3:mini"}]
    })

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.is_closed = False

    with patch.object(ollama_client, "_get_client", return_value=mock_client):
        models = await ollama_client.list_models()

    assert models == ["llama3:latest", "phi3:mini"]
