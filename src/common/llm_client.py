"""LLM Client — unified interface for multi-provider LLM calls."""

import os
import httpx
from typing import Optional

DEFAULT_PROVIDERS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "minimax": {
        "base_url": "https://api.minimaxi.com/v1",
        "api_key_env": "MINIMAX_API_KEY",
    },
}


class LLMClient:
    """Unified LLM client supporting multiple providers with model routing.

    Usage:
        client = LLMClient()
        response = await client.chat(
            messages=[{"role": "user", "content": "Hello"}],
            model="deepseek-chat"
        )
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._client = httpx.AsyncClient(timeout=120.0)

    def _resolve_provider(self, model: str) -> tuple[str, str]:
        """Resolve model string to (base_url, api_key).

        Supports formats:
        - 'deepseek-chat' → looks up provider by prefix
        - 'openrouter/anthropic/claude-sonnet-4' → explicit provider
        - Custom base_url from config overrides
        """
        custom_url = self.config.get("base_url")
        custom_key = self.config.get("api_key")

        if custom_url and custom_key:
            return custom_url.rstrip("/") + "/v1", custom_key

        if "/" in model:
            provider_name, actual_model = model.split("/", 1)
            provider = DEFAULT_PROVIDERS.get(provider_name)
            if provider:
                key = custom_key or os.getenv(provider["api_key_env"])
                return provider["base_url"], key or ""

        # Infer provider from model name prefix
        for prefix, provider in [("deepseek", "deepseek"), ("gpt", "openai"),
                                  ("claude", "openrouter"), ("gemini", "openrouter"),
                                  ("minimax", "minimax"), ("m2", "minimax")]:
            if model.lower().startswith(prefix):
                info = DEFAULT_PROVIDERS[provider]
                key = os.getenv(info["api_key_env"])
                return info["base_url"], key or ""

        # Default to openrouter
        info = DEFAULT_PROVIDERS["openrouter"]
        key = os.getenv(info["api_key_env"])
        return info["base_url"], key or ""

    async def chat(
        self,
        messages: list[dict],
        model: str = "deepseek-chat",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        reasoning_effort: Optional[str] = None,
    ) -> str:
        """Send a chat completion request and return the response text.

        For DeepSeek thinking mode:
        - Set reasoning_effort="max" for complex Agent tasks
        - When reasoning_effort is set, temperature is auto-excluded
          (thinking mode does not support temperature/top_p)
        """
        base_url, api_key = self._resolve_provider(model)

        if not api_key:
            raise ValueError(
                f"No API key found for model '{model}'. "
                f"Set the appropriate environment variable."
            )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Extract clean model name (strip provider prefix)
        clean_model = model.split("/", 1)[-1] if "/" in model else model

        payload: dict = {
            "model": clean_model,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
            payload["extra_body"] = {"thinking": {"type": "enabled"}}
            # Thinking mode does not support temperature/top_p
        else:
            payload["temperature"] = temperature

        try:
            response = await self._client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_detail = e.response.text
            except Exception:
                error_detail = str(e)
            raise RuntimeError(
                f"LLM API error ({e.response.status_code}): {error_detail}"
            ) from e
        except Exception as e:
            raise RuntimeError(f"LLM request failed: {e}") from e

    async def close(self):
        await self._client.aclose()
