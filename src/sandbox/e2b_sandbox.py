"""E2B cloud sandbox implementation — runs code in isolated cloud environments."""

import os
from typing import Optional

from e2b_code_interpreter import AsyncSandbox as E2BSandboxClient

from .base import Sandbox, SandboxResult


class E2BSandbox(Sandbox):
    """E2B cloud sandbox — secure, ephemeral, cloud-hosted code execution.

    Requires E2B_API_KEY environment variable.
    Each sandbox instance is isolated and auto-destroyed on cleanup.
    Uses AsyncSandbox API (run_code, files.read/write).
    """

    def __init__(self, api_key: Optional[str] = None, template: str = "base"):
        self.api_key = api_key or os.getenv("E2B_API_KEY", "")
        self.template = template
        self._sandbox: Optional[E2BSandboxClient] = None

    async def _ensure_sandbox(self) -> E2BSandboxClient:
        """Lazy-init the sandbox on first use."""
        if self._sandbox is None:
            # Sandbox reads API key from environment; set it if provided
            if self.api_key and not os.environ.get("E2B_API_KEY"):
                os.environ["E2B_API_KEY"] = self.api_key
            elif not self.api_key and not os.environ.get("E2B_API_KEY"):
                raise RuntimeError(
                    "E2B_API_KEY not configured. Set the environment variable or pass api_key."
                )
            self._sandbox = await E2BSandboxClient.create()
        return self._sandbox

    def _exec_to_result(self, result, default_success=True) -> SandboxResult:
        """Convert an E2B Execution object to SandboxResult."""
        success = default_success
        error = result.error
        if error:
            success = False

        stdout = "".join(result.logs.stdout) if result.logs.stdout else ""
        stderr = "".join(result.logs.stderr) if result.logs.stderr else ""
        if error:
            stderr = stderr + f"\n{error}" if stderr else error

        # If there's a text result, append it to stdout
        if result.text is not None and result.text != "":
            if stdout and not stdout.endswith("\n"):
                stdout += "\n"
            stdout += str(result.text)

        return SandboxResult(
            success=success,
            stdout=stdout,
            stderr=stderr,
            exit_code=0 if success else 1,
            error=error,
        )

    async def run_code(self, code: str, language: str = "python") -> SandboxResult:
        """Run code in the E2B sandbox.

        For Python code, uses run_code() directly.
        For shell commands, prefixes with '!'.
        For other languages, wraps in subprocess call.
        """
        try:
            sbx = await self._ensure_sandbox()

            if language == "python":
                result = await sbx.run_code(code)
                return self._exec_to_result(result)
            elif language in ("bash", "shell", "sh"):
                result = await sbx.run_code(f"!{code}")
                return self._exec_to_result(result)
            else:
                # Other languages: wrap in subprocess
                runner = {"javascript": "node", "typescript": "node"}.get(
                    language, "python3"
                )
                wrapped = (
                    f"!cat > /tmp/script.py << 'EOF'\n{code}\nEOF\n"
                    f"{runner} /tmp/script.py"
                )
                result = await sbx.run_code(wrapped)
                return self._exec_to_result(result)

        except RuntimeError as e:
            return SandboxResult(
                success=False, error=str(e), exit_code=-1
            )
        except Exception as e:
            return SandboxResult(
                success=False, error=f"E2B execution failed: {e}", exit_code=-1
            )

    async def run_file(self, file_path: str, language: str = "python") -> SandboxResult:
        """Run a file inside the sandbox using run_code."""
        try:
            sbx = await self._ensure_sandbox()

            if language == "python":
                result = await sbx.run_code(
                    f"!python3 {file_path}"
                )
                return self._exec_to_result(result)
            else:
                runner = {"javascript": "node", "typescript": "node"}.get(
                    language, "python3"
                )
                result = await sbx.run_code(f"!{runner} {file_path}")
                return self._exec_to_result(result)

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
            result = await sbx.run_code(
                f"!pip install {' '.join(deps)}"
            )
            return self._exec_to_result(result)
        except Exception as e:
            return SandboxResult(
                success=False, error=f"E2B install failed: {e}", exit_code=-1
            )

    async def write_file(self, path: str, content: str) -> bool:
        """Write a file into the sandbox filesystem using files.write."""
        try:
            sbx = await self._ensure_sandbox()
            await sbx.files.write(path, content)
            return True
        except Exception:
            return False

    async def read_file(self, path: str) -> Optional[str]:
        """Read a file from the sandbox filesystem using files.read."""
        try:
            sbx = await self._ensure_sandbox()
            content = await sbx.files.read(path)
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
