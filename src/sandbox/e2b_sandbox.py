"""E2B cloud sandbox implementation."""

from .base import Sandbox


class E2BSandbox(Sandbox):
    async def run_code(self, code: str, language: str) -> dict:
        raise NotImplementedError("Stage 1 implementation")

    async def install_deps(self, deps: list[str]) -> dict:
        raise NotImplementedError("Stage 1 implementation")

    async def cleanup(self):
        pass
