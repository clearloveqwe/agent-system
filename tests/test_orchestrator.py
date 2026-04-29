"""Tests for Orchestrator."""

from unittest.mock import AsyncMock, patch

import pytest

from src.orchestrator.orchestrator import Orchestrator


class TestOrchestrator:
    """Unit tests for Orchestrator (no actual LLM calls)."""

    @pytest.fixture
    def orchestrator(self):
        return Orchestrator()

    @pytest.mark.asyncio
    async def test_plan_success(self, orchestrator):
        mock_plan = (
            '{"summary": "Build a todo API", '
            '"files": [{"path": "app.py", "language": "python", '
            '"purpose": "Main API entry point", "dependencies": []}], '
            '"test_strategy": "Run pytest"}'
        )
        orchestrator.planner_llm.chat = AsyncMock(return_value=mock_plan)

        result = await orchestrator._plan("Build a simple API")

        assert result["success"]
        assert result["summary"] == "Build a todo API"
        assert len(result["files"]) == 1
        assert result["files"][0]["path"] == "app.py"

    @pytest.mark.asyncio
    async def test_plan_invalid_json(self, orchestrator):
        orchestrator.planner_llm.chat = AsyncMock(return_value="not json")

        result = await orchestrator._plan("Build something")

        assert not result["success"]
        assert "Plan parsing failed" in result["error"]

    @pytest.mark.asyncio
    async def test_run_full_cycle(self, orchestrator, tmp_path):
        mock_plan = (
            '{"summary": "Build a hello world app", '
            '"files": [{"path": "hello.py", "language": "python", '
            '"purpose": "Print hello world", "dependencies": []}], '
            '"test_strategy": "Run it"}'
        )
        orchestrator.planner_llm.chat = AsyncMock(return_value=mock_plan)
        orchestrator.code_agent.llm.chat = AsyncMock(return_value="print('hello')")

        # Change to tmp dir so files are written there
        import os
        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        try:
            result = await orchestrator.run("Build hello world")

            assert result["success"]
            assert result["summary"] == "Build a hello world app"
            assert result["total_files"] == 1
            assert result["files"][0]["path"] == "hello.py"
            assert result["files"][0]["success"]
            assert result["total_lines"] == 1
        finally:
            os.chdir(original_cwd)
