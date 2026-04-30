"""E2B cloud sandbox implementation — runs code in isolated cloud environments."""

import os
from typing import Optional

from e2b_code_interpreter import Sandbox as E2BSandboxClient

from .base import Sandbox, SandboxResult

LANGUAGE_MAP = {
    "python": "python3",
    "javascript": "node",
    "typescript": "node",
    "bash": "bash",
    "shell": "bash",
    "sh": "bash",
}


class E2BSandbox(Sandbox):
    """E2B cloud sandbox — secure, ephemeral, cloud-hosted code execution.

    Requires E2B_API_KEY environment variable.
    Each sandbox instance is isolated and auto-destroyed on cleanup.
    """

    def __init__(self, api_key: Optional[str] = None, template: str = "base"):
        self.api_key = api_key or os.getenv("E2B_API_KEY", "")
        self.template = template
        self._sandbox: Optional[E2BSandboxClient] = None

    async def _ensure_sandbox(self) -> E2BSandboxClient:
        """Lazy-init the sandbox on first use."""
        if self._sandbox is None:
            if not self.api_key:
                raise RuntimeError(
                    "E2B_API_KEY not configured. Set the environment variable or pass api_key."
                )
            self._sandbox = await E2BSandboxClient.create(
                api_key=self.api_key,
                template=self.template,
            )
        return self._sandbox

    async def run_code(self, code: str, language: str = "python") -> SandboxResult:
        """Run code in the E2B sandbox."""
        try:
            sbx = await self._ensure_sandbox()
            cmd = LANGUAGE_MAP.get(language, "python3")
            result = await sbx.commands.run(f"{cmd} -c \"\"\"{code}\"\"\"")
            return SandboxResult(
                success=result.exit_code == 0,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                exit_code=result.exit_code,
            )
        except RuntimeError as e:
            return SandboxResult(
                success=False, error=str(e), exit_code=-1
            )
        except Exception as e:
            return SandboxResult(
                success=False, error=f"E2B execution failed: {e}", exit_code=-1
            )

    async def run_file(self, file_path: str, language: str = "python") -> SandboxResult:
        """Run a file inside the sandbox."""
        try:
            sbx = await self._ensure_sandbox()
            cmd = LANGUAGE_MAP.get(language, "python3")
            result = await sbx.commands.run(f"{cmd} {file_path}")
            return SandboxResult(
                success=result.exit_code == 0,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                exit_code=result.exit_code,
            )
        except Exception as e:
            return SandboxResult(
                success=False, error=f"E2B file execution failed: {e}", exit_code=-1
            )

    async def install_deps(self, deps: list[str]) -> SandboxResult:
        """Install pip dependencies in the sandbox."""
        if not deps:
            return SandboxResult(success=True, stdout="No dependencies to install.")
        try:
            sbx = await self._ensure_sandbox()
            result = await sbx.commands.run(
                f"pip install {' '.join(deps)}"
            )
            return SandboxResult(
                success=result.exit_code == 0,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                exit_code=result.exit_code,
            )
        except Exception as e:
            return SandboxResult(
                success=False, error=f"E2B install failed: {e}", exit_code=-1
            )

    async def write_file(self, path: str, content: str) -> bool:
        """Write a file into the sandbox filesystem."""
        try:
            sbx = await self._ensure_sandbox()
            await sbx.filesystem.write(path, content)
            return True
        except Exception:
            return False

    async def read_file(self, path: str) -> Optional[str]:
        """Read a file from the sandbox filesystem."""
        try:
            sbx = await self._ensure_sandbox()
            content = await sbx.filesystem.read(path)
            return content
        except Exception:
            return None

    async def cleanup(self):
        """Kill the sandbox and release all resources."""
        if self._sandbox:
            try:
                await self._sandbox.kill()
            except Exception:
                pass
            self._sandbox = None
