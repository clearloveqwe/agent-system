"""Local Docker sandbox implementation — runs code in disposable containers."""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .base import Sandbox, SandboxResult

LANGUAGE_IMAGES = {
    "python": "python:3.12-slim",
    "javascript": "node:20-slim",
    "typescript": "node:20-slim",
    "bash": "ubuntu:24.04",
    "shell": "ubuntu:24.04",
}

class DockerSandbox(Sandbox):
    """Local Docker sandbox — runs code in ephemeral Docker containers.

    Each run creates a new container that is auto-removed on exit.
    Requires Docker daemon to be running.
    """

    def __init__(self, image: Optional[str] = None, network_disabled: bool = False):
        self.default_image = image
        self.network_disabled = network_disabled
        self._workdir: Optional[Path] = None

    @property
    def workdir(self) -> Path:
        if self._workdir is None:
            self._workdir = Path(tempfile.mkdtemp(prefix="sandbox_"))
        return self._workdir

    def _docker_run(
        self, image: str, cmd: list[str], cwd: str
    ) -> subprocess.CompletedProcess:
        """Run a command inside a disposable Docker container."""
        docker_cmd = [
            "docker", "run", "--rm",
            "-v", f"{cwd}:/workspace",
            "-w", "/workspace",
        ]
        if self.network_disabled:
            docker_cmd.append("--network=none")
        docker_cmd.extend([image] + cmd)

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return result
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                args=docker_cmd,
                returncode=-1,
                stdout="",
                stderr="Command timed out (120s)",
            )
        except FileNotFoundError:
            return subprocess.CompletedProcess(
                args=docker_cmd,
                returncode=-1,
                stdout="",
                stderr="Docker not found. Install Docker or use E2B sandbox.",
            )

    async def run_code(self, code: str, language: str = "python") -> SandboxResult:
        """Write code to a temp file and run in Docker container."""
        image = self.default_image or LANGUAGE_IMAGES.get(language, "python:3.12-slim")

        # Write code to a file in the workdir
        ext = {"python": ".py", "javascript": ".js", "typescript": ".ts", "bash": ".sh"}
        code_file = self.workdir / f"script{ext.get(language, '.py')}"
        code_file.write_text(code)

        # Build command to run the file
        runner = {"python": "python3", "javascript": "node",
                  "typescript": "node", "bash": "bash", "shell": "sh"}
        run_cmd = [runner.get(language, "python3"), code_file.name]

        result = self._docker_run(image, run_cmd, str(self.workdir))
        return SandboxResult(
            success=result.returncode == 0,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            exit_code=result.returncode,
        )

    async def run_file(self, file_path: str, language: str = "python") -> SandboxResult:
        """Run a local file inside a Docker container."""
        image = self.default_image or LANGUAGE_IMAGES.get(language, "python:3.12-slim")
        runner = {"python": "python3", "javascript": "node",
                  "typescript": "node", "bash": "bash", "shell": "sh"}

        abs_path = os.path.abspath(file_path)
        work_dir = os.path.dirname(abs_path)
        file_name = os.path.basename(abs_path)
        run_cmd = [runner.get(language, "python3"), file_name]

        result = self._docker_run(image, run_cmd, work_dir)
        return SandboxResult(
            success=result.returncode == 0,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            exit_code=result.returncode,
        )

    async def install_deps(self, deps: list[str]) -> SandboxResult:
        """Install pip dependencies inside the sandbox workspace."""
        if not deps:
            return SandboxResult(success=True, stdout="No dependencies to install.")
        image = self.default_image or "python:3.12-slim"
        cmd = ["pip", "install"] + deps
        result = self._docker_run(image, cmd, str(self.workdir))
        return SandboxResult(
            success=result.returncode == 0,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            exit_code=result.returncode,
        )

    async def write_file(self, path: str, content: str) -> bool:
        """Write a file to the sandbox workspace."""
        try:
            full_path = self.workdir / path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
            return True
        except Exception:
            return False

    async def read_file(self, path: str) -> Optional[str]:
        """Read a file from the sandbox workspace."""
        try:
            full_path = self.workdir / path
            if full_path.exists():
                return full_path.read_text()
            return None
        except Exception:
            return None

    async def cleanup(self):
        """Remove temporary workspace directory."""
        if self._workdir and self._workdir.exists():
            import shutil
            try:
                shutil.rmtree(self._workdir)
            except Exception:
                pass
            self._workdir = None
