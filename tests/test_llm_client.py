"""Tests for LLMClient."""

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from src.common.llm_client import LLMClient


class TestLLMClient:
    """Unit tests for LLMClient (no actual API calls)."""

    def test_resolve_provider_deepseek(self):
        client = LLMClient()
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}):
            url, key = client._resolve_provider("deepseek-chat")
            assert "api.deepseek.com" in url
            assert key == "sk-test"

    def test_resolve_provider_openrouter_explicit(self):
        client = LLMClient()
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test"}):
            url, key = client._resolve_provider("openrouter/anthropic/claude-sonnet-4")
            assert "openrouter.ai" in url
            assert key == "sk-test"

    def test_resolve_provider_custom(self):
        client = LLMClient({"base_url": "https://custom.api.com", "api_key": "ck-test"})
        url, key = client._resolve_provider("any-model")
        assert "custom.api.com" in url
        assert key == "ck-test"

    def test_resolve_provider_no_key_returns_empty(self):
        client = LLMClient()
        with patch.dict("os.environ", {}, clear=True):
            url, key = client._resolve_provider("unknown-model")
            assert key == ""

    @pytest.mark.asyncio
    async def test_chat_no_api_key_raises(self):
        client = LLMClient()
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="No API key found"):
                await client.chat(messages=[{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_chat_success(self):
        client = LLMClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello, world!"}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}):
            with patch.object(client._client, "post", AsyncMock(return_value=mock_response)):
                result = await client.chat(
                    messages=[{"role": "user", "content": "Say hi"}],
                    model="deepseek-chat",
                )
                assert result == "Hello, world!"

    @pytest.mark.asyncio
    async def test_close(self):
        client = LLMClient()
        with patch.object(client._client, "aclose", AsyncMock()) as mock_close:
            await client.close()
            mock_close.assert_awaited_once()
