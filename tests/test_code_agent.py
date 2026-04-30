"""Tests for CodeAgent."""

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from src.agents.code_agent import CodeAgent


class TestCodeAgent:
    """Unit tests for CodeAgent."""

    @pytest.fixture
    def agent(self):
        return CodeAgent(model_config={"model": "deepseek-chat"})

    def test_init(self, agent):
        assert agent.role == "developer"
        assert agent.model == "deepseek-chat"
        assert agent.reasoning_effort is None

    def test_init_with_reasoning_effort(self):
        agent = CodeAgent(model_config={"model": "deepseek-v4-flash", "reasoning_effort": "max"})
        assert agent.model == "deepseek-v4-flash"
        assert agent.reasoning_effort == "max"

    @pytest.mark.asyncio
    async def test_execute_no_requirement(self, agent):
        result = await agent.execute({})
        assert not result["success"]
        assert "No requirement" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_success(self, agent):
        mock_llm = AsyncMock(return_value="print('hello')")
        agent.llm.chat = mock_llm

        result = await agent.execute({
            "requirement": "Print hello world",
            "language": "python",
        })

        assert result["success"]
        assert result["code"] == "print('hello')"
        assert result["language"] == "python"

    @pytest.mark.asyncio
    async def test_execute_with_target_path(self, agent, tmp_path):
        target = tmp_path / "hello.py"
        mock_llm = AsyncMock(return_value="print('hello')")
        agent.llm.chat = mock_llm

        result = await agent.execute({
            "requirement": "Print hello world",
            "language": "python",
            "target_path": str(target),
        })

        assert result["success"]
        assert result["file_path"] == str(target)
        assert target.read_text() == "print('hello')"

    @pytest.mark.asyncio
    async def test_execute_llm_error(self, agent):
        agent.llm.chat = AsyncMock(side_effect=Exception("API timeout"))

        result = await agent.execute({
            "requirement": "Do something",
            "language": "python",
        })

        assert not result["success"]
        assert "API timeout" in result["error"]

    def test_clean_code_no_fences(self):
        agent = CodeAgent()
        assert agent._clean_code("print('hi')") == "print('hi')"

    def test_clean_code_with_fences(self):
        agent = CodeAgent()
        code = "```python\nprint('hi')\n```"
        assert agent._clean_code(code) == "print('hi')"

    def test_clean_code_with_fences_no_language(self):
        agent = CodeAgent()
        code = "```\nprint('hi')\n```"
        assert agent._clean_code(code) == "print('hi')"
