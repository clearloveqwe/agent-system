"""Sandbox abstraction — execute code in isolated environments."""

from abc import ABC, abstractmethod


class Sandbox(ABC):
    """Abstract sandbox for safe code execution."""

    @abstractmethod
    async def run_code(self, code: str, language: str) -> dict:
        ...

    @abstractmethod
    async def install_deps(self, deps: list[str]) -> dict:
        ...

    @abstractmethod
    async def cleanup(self):
        ...
