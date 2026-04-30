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

    def test_resolve_provider_minimax(self):
        client = LLMClient()
        with patch.dict("os.environ", {"MINIMAX_API_KEY": "mm-test"}):
            url, key = client._resolve_provider("minimax/MiniMax-M2.7")
            assert "api.minimaxi.com" in url
            assert key == "mm-test"

    def test_resolve_provider_minimax_by_prefix(self):
        client = LLMClient()
        with patch.dict("os.environ", {"MINIMAX_API_KEY": "mm-test"}):
            url, key = client._resolve_provider("MiniMax-M2.7")
            assert "api.minimaxi.com" in url
            assert key == "mm-test"

    def test_resolve_provider_minimax_by_M2_prefix(self):
        client = LLMClient()
        with patch.dict("os.environ", {"MINIMAX_API_KEY": "mm-test"}):
            url, key = client._resolve_provider("M2.7")
            assert "api.minimaxi.com" in url
            assert key == "mm-test"

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
    async def test_chat_success_deepseek(self):
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
    async def test_chat_success_minimax(self):
        client = LLMClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Generated code"}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.dict("os.environ", {"MINIMAX_API_KEY": "mm-test"}):
            with patch.object(client._client, "post", AsyncMock(return_value=mock_response)):
                result = await client.chat(
                    messages=[{"role": "user", "content": "Write a React component"}],
                    model="minimax/MiniMax-M2.7",
                )
                assert result == "Generated code"

    @pytest.mark.asyncio
    async def test_chat_with_reasoning_effort_max(self):
        """Verify reasoning_effort=max adds correct payload fields."""
        client = LLMClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Planned architecture"}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}):
            with patch.object(client._client, "post", AsyncMock(return_value=mock_response)) as mock_post:
                result = await client.chat(
                    messages=[{"role": "user", "content": "Design system"}],
                    model="deepseek-v4-flash",
                    reasoning_effort="max",
                )

                # Verify reasoning_effort was included
                call_kwargs = mock_post.call_args[1]
                payload = call_kwargs["json"]
                assert payload["reasoning_effort"] == "max"
                assert payload["extra_body"] == {"thinking": {"type": "enabled"}}
                # temperature should NOT be present when reasoning_effort is set
                assert "temperature" not in payload
                assert result == "Planned architecture"

    @pytest.mark.asyncio
    async def test_close(self):
        client = LLMClient()
        with patch.object(client._client, "aclose", AsyncMock()) as mock_close:
            await client.close()
            mock_close.assert_awaited_once()
