"""Base Agent — abstract class for all agent roles."""

from abc import ABC, abstractmethod


class BaseAgent(ABC):
    """Abstract base for all agent roles."""

    def __init__(self, role: str, model_config: dict = None):
        self.role = role
        self.model_config = model_config or {}

    @abstractmethod
    async def execute(self, task: dict) -> dict:
        """Execute a task and return results."""
        ...
