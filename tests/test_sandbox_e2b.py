"""Tests for E2BSandbox — uses mocked E2B client to avoid cloud dependency."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.sandbox.e2b_sandbox import E2BSandbox


def _mock_execution(text="", stdout=None, stderr=None, error=None):
    """Create a mock E2B Execution object matching the new API."""
    mock = MagicMock()
    mock.text = text
    mock.logs.stdout = stdout or []
    mock.logs.stderr = stderr or []
    mock.error = error
    return mock


class TestE2BSandbox:
    """Unit tests for E2BSandbox with mocked E2B SDK."""

    @pytest.fixture
    def sandbox(self):
        return E2BSandbox(api_key="test-key")

    @pytest.mark.asyncio
    async def test_no_api_key_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            sandbox = E2BSandbox(api_key="")
            result = await sandbox.run_code("print('hi')")
        assert not result.success
        assert "E2B_API_KEY not configured" in result.error

    @pytest.mark.asyncio
    async def test_run_code_success(self, sandbox):
        mock_sbx = AsyncMock()
        # Mock sbx.run_code() to return a successful execution
        mock_sbx.run_code = AsyncMock(return_value=_mock_execution(
            text="Hello from E2B",
            stdout=["Hello from E2B\n"],
        ))
        sandbox._sandbox = mock_sbx

        result = await sandbox.run_code("print('hello')", language="python")
        assert result.success
        assert "Hello from E2B" in result.stdout

    @pytest.mark.asyncio
    async def test_run_code_failure(self, sandbox):
        mock_sbx = AsyncMock()
        mock_sbx.run_code = AsyncMock(return_value=_mock_execution(
            error="ZeroDivisionError: division by zero",
            stderr=["ZeroDivisionError: division by zero\n"],
        ))
        sandbox._sandbox = mock_sbx

        result = await sandbox.run_code("1/0", language="python")
        assert not result.success
        assert "division" in result.stderr

    @pytest.mark.asyncio
    async def test_run_code_with_text_result(self, sandbox):
        """When code returns a value, it should appear in stdout."""
        mock_sbx = AsyncMock()
        mock_sbx.run_code = AsyncMock(return_value=_mock_execution(
            text="42",
            stdout=["42\n"],
        ))
        sandbox._sandbox = mock_sbx

        result = await sandbox.run_code("21 + 21", language="python")
        assert result.success
        assert "42" in result.stdout

    @pytest.mark.asyncio
    async def test_run_shell_command(self, sandbox):
        mock_sbx = AsyncMock()
        mock_sbx.run_code = AsyncMock(return_value=_mock_execution(
            stdout=["total 4\n-rw-r--r-- 1 user user 0 file.txt\n"],
        ))
        sandbox._sandbox = mock_sbx

        result = await sandbox.run_code("ls -la", language="bash")
        assert result.success
        assert "file.txt" in result.stdout

    @pytest.mark.asyncio
    async def test_run_file(self, sandbox):
        mock_sbx = AsyncMock()
        mock_sbx.run_code = AsyncMock(return_value=_mock_execution(
            stdout=["Hello from file\n"],
        ))
        sandbox._sandbox = mock_sbx

        result = await sandbox.run_file("/home/user/test.py", language="python")
        assert result.success
        assert "Hello" in result.stdout

    @pytest.mark.asyncio
    async def test_install_deps(self, sandbox):
        mock_sbx = AsyncMock()
        mock_sbx.run_code = AsyncMock(return_value=_mock_execution(
            stdout=["Installed httpx, pydantic\n"],
        ))
        sandbox._sandbox = mock_sbx

        result = await sandbox.install_deps(["httpx", "pydantic"])
        assert result.success
        assert "Installed" in result.stdout

    @pytest.mark.asyncio
    async def test_install_deps_empty(self, sandbox):
        result = await sandbox.install_deps([])
        assert result.success
        assert "No dependencies" in result.stdout

    @pytest.mark.asyncio
    async def test_write_and_read_file(self, sandbox):
        mock_sbx = AsyncMock()
        mock_sbx.files.write = AsyncMock(return_value=None)
        mock_sbx.files.read = AsyncMock(return_value="file content")
        sandbox._sandbox = mock_sbx

        assert await sandbox.write_file("test.txt", "hello")
        content = await sandbox.read_file("test.txt")
        assert content == "file content"

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, sandbox):
        mock_sbx = AsyncMock()
        mock_sbx.files.read = AsyncMock(side_effect=Exception("Not found"))
        sandbox._sandbox = mock_sbx

        content = await sandbox.read_file("nonexistent.txt")
        assert content is None

    @pytest.mark.asyncio
    async def test_cleanup(self, sandbox):
        mock_sbx = AsyncMock()
        mock_sbx.kill = AsyncMock()
        sandbox._sandbox = mock_sbx

        await sandbox.cleanup()
        mock_sbx.kill.assert_awaited_once()
        assert sandbox._sandbox is None

    @pytest.mark.asyncio
    async def test_cleanup_no_sandbox(self, sandbox):
        """Cleanup should not fail when no sandbox was created."""
        sandbox._sandbox = None
        await sandbox.cleanup()  # Should not raise
