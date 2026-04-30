"""Tests for E2BSandbox — uses mocked E2B client to avoid cloud dependency."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.sandbox.e2b_sandbox import E2BSandbox


class TestE2BSandbox:
    """Unit tests for E2BSandbox with mocked E2B SDK."""

    @pytest.fixture
    def sandbox(self):
        return E2BSandbox(api_key="test-key")

    @pytest.mark.asyncio
    async def test_no_api_key_raises(self):
        sandbox = E2BSandbox(api_key="")
        with patch.dict("os.environ", {}, clear=True):
            result = await sandbox.run_code("print('hi')")
        assert not result.success
        assert "E2B_API_KEY not configured" in result.error

    @pytest.mark.asyncio
    async def test_run_code_success(self, sandbox):
        mock_sbx = AsyncMock()
        mock_cmd_result = MagicMock()
        mock_cmd_result.exit_code = 0
        mock_cmd_result.stdout = "Hello from E2B"
        mock_cmd_result.stderr = ""
        mock_sbx.commands.run = AsyncMock(return_value=mock_cmd_result)
        sandbox._sandbox = mock_sbx

        result = await sandbox.run_code("print('hello')", language="python")
        assert result.success
        assert "Hello from E2B" in result.stdout

    @pytest.mark.asyncio
    async def test_run_code_failure(self, sandbox):
        mock_sbx = AsyncMock()
        mock_cmd_result = MagicMock()
        mock_cmd_result.exit_code = 1
        mock_cmd_result.stdout = ""
        mock_cmd_result.stderr = "Error: division by zero"
        mock_sbx.commands.run = AsyncMock(return_value=mock_cmd_result)
        sandbox._sandbox = mock_sbx

        result = await sandbox.run_code("1/0", language="python")
        assert not result.success
        assert "division" in result.stderr

    @pytest.mark.asyncio
    async def test_install_deps(self, sandbox):
        mock_sbx = AsyncMock()
        mock_cmd_result = MagicMock()
        mock_cmd_result.exit_code = 0
        mock_cmd_result.stdout = "Installed"
        mock_cmd_result.stderr = ""
        mock_sbx.commands.run = AsyncMock(return_value=mock_cmd_result)
        sandbox._sandbox = mock_sbx

        result = await sandbox.install_deps(["httpx", "pydantic"])
        assert result.success

    @pytest.mark.asyncio
    async def test_write_and_read_file(self, sandbox):
        mock_sbx = AsyncMock()
        mock_sbx.filesystem.write = AsyncMock(return_value=None)
        mock_sbx.filesystem.read = AsyncMock(return_value="file content")
        sandbox._sandbox = mock_sbx

        assert await sandbox.write_file("test.txt", "hello")
        content = await sandbox.read_file("test.txt")
        assert content == "file content"

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
