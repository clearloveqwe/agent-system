"""Tests for Orchestrator — end-to-end pipeline."""

from unittest.mock import AsyncMock

import pytest

from src.orchestrator.orchestrator import Orchestrator, PipelineResult, PipelineFileResult
from src.sandbox.base import SandboxResult


# ── Shared fixtures ──────────────────────────────────────────────


@pytest.fixture
def orchestrator():
    """Basic orchestrator with no sandbox or KB."""
    return Orchestrator()


@pytest.fixture
def mock_sandbox():
    """Mock sandbox that always succeeds."""
    sb = AsyncMock()
    sb.write_file = AsyncMock(return_value=True)
    sb.read_file = AsyncMock(return_value="print('hello')")
    sb.run_file = AsyncMock(return_value=SandboxResult(
        success=True, stdout="OK\n", exit_code=0,
    ))
    sb.install_deps = AsyncMock(return_value=SandboxResult(
        success=True, stdout="", exit_code=0,
    ))
    sb.run_code = AsyncMock(return_value=SandboxResult(
        success=True, stdout="All tests passed\n", exit_code=0,
    ))
    sb.cleanup = AsyncMock()
    return sb


@pytest.fixture
def mock_kb():
    """Mock knowledge base."""
    kb = AsyncMock()
    kb.store = AsyncMock(return_value="entry-1")
    kb.search = AsyncMock(return_value=[])
    return kb


# ── Plan step tests ──────────────────────────────────────────────


class TestOrchestratorPlan:
    """Unit tests for the planning step (no LLM calls)."""

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
    async def test_plan_missing_key(self, orchestrator):
        orchestrator.planner_llm.chat = AsyncMock(
            return_value='{"summary": "test", "files": []}'
        )

        result = await orchestrator._plan("Build something")

        assert not result["success"]
        assert "missing key" in result["error"]


# ── Generate-with-retry step tests ────────────────────────────────


class TestOrchestratorPipelineGenerate:
    """Tests for generate-with-retry pipeline step."""

    @pytest.mark.asyncio
    async def test_generate_file_success_no_sandbox(self):
        """Without sandbox, generation should succeed on first attempt."""
        orchestrator = Orchestrator()
        orchestrator.code_agent.execute = AsyncMock(return_value={
            "success": True, "code": "print('hello')", "file_path": "/tmp/hello.py",
            "language": "python", "lines": 1,
        })

        file_spec = {
            "path": "hello.py", "language": "python",
            "purpose": "Print hello world", "dependencies": [],
        }
        result = await orchestrator._generate_file_with_retry(
            file_spec, "Test project", ["hello.py"]
        )

        assert result.success
        assert result.path == "hello.py"
        assert result.lines == 1
        assert result.attempts == 1
        assert not result.sandbox_tested

    @pytest.mark.asyncio
    async def test_generate_file_with_sandbox_passes(self, mock_sandbox):
        """With sandbox, file should be written and tested."""
        orchestrator = Orchestrator(sandbox=mock_sandbox)
        orchestrator.code_agent.execute = AsyncMock(return_value={
            "success": True, "code": "print('hello')", "file_path": "/tmp/h.py",
            "language": "python", "lines": 1,
        })

        result = await orchestrator._generate_file_with_retry(
            {"path": "hello.py", "language": "python",
             "purpose": "Print hello", "dependencies": []},
            "Test project", ["hello.py"],
        )

        assert result.success
        assert result.sandbox_tested
        assert result.sandbox_passed is True
        assert result.sandbox_output == "OK\n"
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_generate_file_heals_on_failure(self):
        """When sandbox test fails, healer should retry with error context."""
        sandbox = AsyncMock()
        sandbox.write_file = AsyncMock(return_value=True)
        # First two runs fail, third succeeds
        sandbox.run_file = AsyncMock(side_effect=[
            SandboxResult(success=False, stderr="SyntaxError: invalid syntax",
                          stdout="", exit_code=1),
            SandboxResult(success=False, stderr="NameError: x not defined",
                          stdout="", exit_code=1),
            SandboxResult(success=True, stdout="All good\n", exit_code=0),
        ])

        orchestrator = Orchestrator(sandbox=sandbox, config={
            "code_agent": {"model": "test-model"},
        })
        # Generation always succeeds
        orchestrator.code_agent.execute = AsyncMock(return_value={
            "success": True, "code": "print('fixed')", "file_path": "/tmp/f.py",
            "language": "python", "lines": 1,
        })

        result = await orchestrator._generate_file_with_retry(
            {"path": "fix.py", "language": "python",
             "purpose": "Fix test", "dependencies": []},
            "Test project", ["fix.py"],
        )

        assert result.success
        assert result.sandbox_tested
        assert result.sandbox_passed is True
        assert result.attempts == 3

    @pytest.mark.asyncio
    async def test_generate_file_exhausts_retries(self):
        """When all sandbox attempts fail, result should report failure."""
        sandbox = AsyncMock()
        sandbox.write_file = AsyncMock(return_value=True)
        sandbox.run_file = AsyncMock(return_value=SandboxResult(
            success=False, stderr="Always fails", stdout="", exit_code=1,
        ))

        orchestrator = Orchestrator(sandbox=sandbox)
        orchestrator.code_agent.execute = AsyncMock(return_value={
            "success": True, "code": "bad code", "file_path": "/tmp/b.py",
            "language": "python", "lines": 1,
        })

        result = await orchestrator._generate_file_with_retry(
            {"path": "bad.py", "language": "python",
             "purpose": "Bad file", "dependencies": []},
            "Test project", ["bad.py"],
        )

        assert not result.sandbox_passed
        assert result.sandbox_error == "Always fails"
        assert result.attempts == 3

    @pytest.mark.asyncio
    async def test_generation_failure(self):
        """If code generation itself fails, return error without retry."""
        orchestrator = Orchestrator()
        orchestrator.code_agent.execute = AsyncMock(return_value={
            "success": False, "error": "LLM call failed",
        })

        result = await orchestrator._generate_file_with_retry(
            {"path": "fail.py", "language": "python",
             "purpose": "Fails", "dependencies": []},
            "Test project", ["fail.py"],
        )

        assert not result.success
        assert "LLM call failed" in result.error
        assert result.attempts == 1


# ── Full pipeline integration tests ───────────────────────────────


class TestOrchestratorPipelineRun:
    """Integration tests for the full pipeline (all mocked)."""

    @pytest.mark.asyncio
    async def test_run_full_cycle_no_sandbox(self, tmp_path):
        """Full cycle without sandbox should generate files."""
        orchestrator = Orchestrator()
        orchestrator.planner_llm.chat = AsyncMock(return_value=(
            '{"summary": "Build a hello world app", '
            '"files": [{"path": "hello.py", "language": "python", '
            '"purpose": "Print hello world", "dependencies": []}], '
            '"test_strategy": "Run it"}'
        ))
        orchestrator.code_agent.llm.chat = AsyncMock(return_value="print('hello')")

        import os
        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        try:
            result = await orchestrator.run("Build hello world")

            assert isinstance(result, PipelineResult)
            assert result.success
            assert result.summary == "Build a hello world app"
            assert len(result.files) == 1
            assert result.files[0].path == "hello.py"
            assert result.files[0].success
            assert result.pipeline_test_result is None  # no sandbox
            assert result.total_attempts == 1
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio
    async def test_run_full_cycle_with_sandbox(self, mock_sandbox, tmp_path):
        """Full cycle with sandbox should test files."""
        orchestrator = Orchestrator(sandbox=mock_sandbox)
        orchestrator.planner_llm.chat = AsyncMock(return_value=(
            '{"summary": "Build a todo API", '
            '"files": [{"path": "app.py", "language": "python", '
            '"purpose": "Main API", "dependencies": []}, '
            '{"path": "tests/test_app.py", "language": "python", '
            '"purpose": "Test the API", "dependencies": ["app.py"]}], '
            '"test_strategy": "Run pytest tests/"}'
        ))
        orchestrator.code_agent.execute = AsyncMock(return_value={
            "success": True, "code": "def foo(): pass",
            "file_path": str(tmp_path / "test_file.py"),
            "language": "python", "lines": 1,
        })

        result = await orchestrator.run("Build a todo API")

        assert result.success
        assert len(result.files) == 2
        assert result.pipeline_test_result is not None
        assert result.pipeline_test_result.success
        # Each file was attempted once + pipeline test
        assert result.total_attempts == 2

    @pytest.mark.asyncio
    async def test_run_fails_on_bad_plan(self):
        """If planning fails, pipeline should stop early."""
        orchestrator = Orchestrator()
        orchestrator.planner_llm.chat = AsyncMock(return_value="invalid json")

        result = await orchestrator.run("Build something")

        assert not result.success
        assert "Plan parsing failed" in result.error

    @pytest.mark.asyncio
    async def test_run_with_knowledge_base_stores_results(
        self, mock_sandbox, mock_kb, tmp_path
    ):
        """When KB is provided, successful results should be stored."""
        orchestrator = Orchestrator(sandbox=mock_sandbox, knowledge_base=mock_kb)
        orchestrator.planner_llm.chat = AsyncMock(return_value=(
            '{"summary": "Build hello", '
            '"files": [{"path": "hello.py", "language": "python", '
            '"purpose": "Print hello", "dependencies": []}], '
            '"test_strategy": "Run it"}'
        ))
        orchestrator.code_agent.execute = AsyncMock(return_value={
            "success": True, "code": "print('hello')",
            "file_path": str(tmp_path / "hello.py"),
            "language": "python", "lines": 1,
        })

        result = await orchestrator.run("Write hello world")

        assert result.success
        assert result.kb_stored
        mock_kb.store.assert_called()

    @pytest.mark.asyncio
    async def test_run_healing_loop_with_sandbox(self, tmp_path):
        """Pipeline should heal when sandbox tests fail initially."""
        sandbox = AsyncMock()
        sandbox.write_file = AsyncMock(return_value=True)
        sandbox.read_file = AsyncMock(return_value="print('fixed')")
        # First file pass, second file fail twice then heal + pipeline test
        sandbox.run_file = AsyncMock(side_effect=[
            SandboxResult(success=True, stdout="OK\n", exit_code=0),   # app.py ✓
            SandboxResult(success=False, stderr="AssertionError", stdout="",
                          exit_code=1),                                 # test_app.py #1 ✗
            SandboxResult(success=False, stderr="AssertionError", stdout="",
                          exit_code=1),                                 # test_app.py #2 ✗
            SandboxResult(success=True, stdout="Fixed\n", exit_code=0), # test_app.py #3 ✓
            SandboxResult(success=True, stdout="PASS\n", exit_code=0),  # pipeline test ✓
        ])
        sandbox.install_deps = AsyncMock(return_value=SandboxResult(
            success=True, stdout="", exit_code=0,
        ))
        sandbox.run_code = AsyncMock(return_value=SandboxResult(
            success=True, stdout="All tests passed\n", exit_code=0,
        ))

        orchestrator = Orchestrator(sandbox=sandbox)
        orchestrator.planner_llm.chat = AsyncMock(return_value=(
            '{"summary": "Build hello", '
            '"files": [{"path": "app.py", "language": "python", '
            '"purpose": "Main app", "dependencies": []}, '
            '{"path": "tests/test_app.py", "language": "python", '
            '"purpose": "Test app", "dependencies": ["app.py"]}], '
            '"test_strategy": "Run pytest tests/"}'
        ))
        # Code generation always succeeds
        orchestrator.code_agent.execute = AsyncMock(return_value={
            "success": True, "code": "print('code')",
            "file_path": str(tmp_path / "code.py"),
            "language": "python", "lines": 1,
        })

        result = await orchestrator.run("Build app with tests")

        # Overall should succeed (healing worked)
        assert result.success
        assert len(result.files) == 2
        # First file succeeded on attempt 1
        assert result.files[0].success
        assert result.files[0].attempts == 1
        # Second file took 3 attempts (2 fails + 1 heal success)
        assert result.files[1].attempts == 3


# ── Data class tests ──────────────────────────────────────────────


class TestPipelineFileResult:
    """Tests for PipelineFileResult data class."""

    def test_to_dict(self):
        r = PipelineFileResult(
            path="test.py", language="python", purpose="Testing",
            success=True, lines=10, file_path="/tmp/test.py",
            sandbox_tested=True, sandbox_passed=True,
            sandbox_output="OK", sandbox_error="", attempts=2,
        )
        d = r.to_dict()
        assert d["path"] == "test.py"
        assert d["success"]
        assert d["sandbox_passed"]
        assert d["attempts"] == 2


class TestPipelineResult:
    """Tests for PipelineResult data class."""

    def test_to_dict_no_test(self):
        r = PipelineResult(
            success=True, summary="Test", files=[],
            test_strategy="Run", total_duration=1.5, total_attempts=3,
        )
        d = r.to_dict()
        assert d["success"]
        assert d["total_duration_seconds"] == 1.5
        assert d["total_attempts"] == 3
        assert d["pipeline_test_passed"] is None

    def test_to_dict_with_test(self):
        r = PipelineResult(
            success=True, summary="Test", files=[],
            pipeline_test_result=SandboxResult(True, stdout="OK"),
            total_duration=2.0, total_attempts=1,
        )
        d = r.to_dict()
        assert d["pipeline_test_passed"] is True
        assert d["pipeline_test_stdout"] == "OK"
