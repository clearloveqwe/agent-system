"""Tests for DockerSandbox — uses mocked subprocess to avoid Docker dependency."""

from unittest.mock import patch, MagicMock

import pytest

from src.sandbox.docker_sandbox import DockerSandbox


class TestDockerSandbox:
    """Unit tests for DockerSandbox with mocked subprocess."""

    @pytest.fixture
    def sandbox(self):
        return DockerSandbox()

    @pytest.mark.asyncio
    async def test_run_code_success(self, sandbox):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Hello, World!\n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = await sandbox.run_code("print('hello')", language="python")

        assert result.success
        assert "Hello" in result.stdout
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_run_code_failure(self, sandbox):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "SyntaxError: invalid syntax"

        with patch("subprocess.run", return_value=mock_result):
            result = await sandbox.run_code("print(", language="python")

        assert not result.success
        assert "SyntaxError" in result.stderr
        assert result.exit_code == 1

    @pytest.mark.asyncio
    async def test_run_code_timeout(self, sandbox):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="test", timeout=1)):
            result = await sandbox.run_code("while True: pass", language="python")
            assert not result.success
            assert "timed out" in result.stderr.lower() or "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_docker_not_found(self, sandbox):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            result = await sandbox.run_code("print('hi')", language="python")
            assert not result.success
            assert "Docker not found" in result.stderr

    @pytest.mark.asyncio
    async def test_write_and_read_file(self, sandbox):
        assert await sandbox.write_file("test.txt", "hello")
        content = await sandbox.read_file("test.txt")
        assert content == "hello"

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, sandbox):
        content = await sandbox.read_file("nonexistent.txt")
        assert content is None

    @pytest.mark.asyncio
    async def test_cleanup(self, sandbox):
        await sandbox.write_file("temp.txt", "data")
        assert sandbox._workdir is not None
        assert sandbox._workdir.exists()
        await sandbox.cleanup()
        assert sandbox._workdir is None

    @pytest.mark.asyncio
    async def test_install_deps_empty(self, sandbox):
        result = await sandbox.install_deps([])
        assert result.success
        assert "No dependencies" in result.stdout

    @pytest.mark.asyncio
    async def test_install_deps_success(self, sandbox):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Successfully installed requests"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = await sandbox.install_deps(["requests"])
        assert result.success

    @pytest.mark.asyncio
    async def test_run_file(self, sandbox, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("print('from file')")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "from file\n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = await sandbox.run_file(str(test_file), language="python")
        assert result.success
        assert "from file" in result.stdout
