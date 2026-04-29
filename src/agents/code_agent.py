"""CodeAgent — generates, modifies, and tests code for a specific domain."""

from .base import BaseAgent


class CodeAgent(BaseAgent):
    """Agent specialized in code generation and modification."""

    async def execute(self, task: dict) -> dict:
        raise NotImplementedError("Stage 1 implementation")
