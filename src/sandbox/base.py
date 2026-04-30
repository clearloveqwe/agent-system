"""Sandbox abstraction — execute code in isolated environments."""

from abc import ABC, abstractmethod
from typing import Optional


class SandboxResult:
    """Result from a sandbox code execution."""

    def __init__(
        self,
        success: bool,
        stdout: str = "",
        stderr: str = "",
        exit_code: int = 0,
        error: Optional[str] = None,
    ):
        self.success = success
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.error = error

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "error": self.error,
        }


class Sandbox(ABC):
    """Abstract sandbox for safe code execution."""

    @abstractmethod
    async def run_code(self, code: str, language: str = "python") -> SandboxResult:
        """Run arbitrary code in the sandbox and return results."""
        ...

    @abstractmethod
    async def run_file(self, file_path: str, language: str = "python") -> SandboxResult:
        """Run a file in the sandbox."""
        ...

    @abstractmethod
    async def install_deps(self, deps: list[str]) -> SandboxResult:
        """Install dependencies in the sandbox environment."""
        ...

    @abstractmethod
    async def write_file(self, path: str, content: str) -> bool:
        """Write a file into the sandbox."""
        ...

    @abstractmethod
    async def read_file(self, path: str) -> Optional[str]:
        """Read a file from the sandbox."""
        ...

    @abstractmethod
    async def cleanup(self):
        """Clean up sandbox resources."""
        ...
