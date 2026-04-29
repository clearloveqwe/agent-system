"""LLM Client — unified interface for multi-provider LLM calls."""


class LLMClient:
    """Abstracted LLM client supporting multiple providers with routing."""

    def __init__(self, config: dict = None):
        self.config = config or {}

    async def chat(self, messages: list, model: str = None) -> str:
        raise NotImplementedError("Stage 1 implementation")
