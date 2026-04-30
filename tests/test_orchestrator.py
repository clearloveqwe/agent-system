"""Tests for Orchestrator — end-to-end pipeline with Pydantic structured output."""

from unittest.mock import AsyncMock

import pytest

from src.orchestrator.orchestrator import Orchestrator, PipelineResult, PipelineFileResult
from src.common.schemas import ProjectPlan, PipelineTestResult
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


@pytest.fixture
def valid_plan_json():
    """Valid project plan JSON returned by mocked LLM."""
    return (
        '{"summary": "Build a todo API", '
        '"files": [{"path": "app.py", "language": "python", '
        '"purpose": "Main API entry point", "dependencies": []}], '
        '"test_strategy": "Run pytest"}'
    )


def mock_code_agent_success(code="print('hello')", file_path="/tmp/gen.py"):
    """Helper: create a successful CodeAgent mock return value."""
    return {
        "success": True, "code": code,
        "file_path": file_path, "language": "python", "lines": len(code.splitlines()),
    }


# ── Plan step tests ──────────────────────────────────────────────


class TestOrchestratorPlan:
    """Unit tests for Pydantic-validated planning step."""

    @pytest.mark.asyncio
    async def test_plan_success(self, orchestrator, valid_plan_json):
        """_plan() should return a valid _PlanResult with parsed ProjectPlan."""
        orchestrator.planner_llm.chat = AsyncMock(return_value=valid_plan_json)

        result = await orchestrator._plan("Build a simple API")

        assert result.success
        assert result.corrections == 0
        assert isinstance(result.plan, ProjectPlan)
        assert result.plan.summary == "Build a todo API"
        assert len(result.plan.files) == 1
        assert result.plan.files[0].path == "app.py"
        assert result.plan.test_strategy == "Run pytest"

    @pytest.mark.asyncio
    async def test_plan_invalid_json(self, orchestrator):
        """_plan() should fail and return error after exhausting corrections."""
        orchestrator.planner_llm.chat = AsyncMock(return_value="not json")

        result = await orchestrator._plan("Build something")

        assert not result.success
        assert "failed" in result.error

    @pytest.mark.asyncio
    async def test_plan_missing_key(self, orchestrator):
        """When Pydantic validation fails, _plan() should correct and still fail eventually."""
        orchestrator.planner_llm.chat = AsyncMock(
            return_value='{"summary": "test", "files": []}'
        )

        result = await orchestrator._plan("Build something")

        assert not result.success
        assert "validation failed" in result.error

    @pytest.mark.asyncio
    async def test_plan_auto_corrects(self, orchestrator):
        """When first attempt fails validation, LLM should retry."""
        valid = (
            '{"summary": "Fixed plan", '
            '"files": [{"path": "fix.py", "language": "python", '
            '"purpose": "Fixed", "dependencies": []}], '
            '"test_strategy": "pytest"}'
        )
        # First call returns bad JSON, second returns valid
        orchestrator.planner_llm.chat = AsyncMock(side_effect=[
            '{"summary": "bad"',  # invalid JSON
            valid,                 # valid
        ])

        result = await orchestrator._plan("Build something")

        assert result.success
        assert result.corrections == 1
        assert result.plan.summary == "Fixed plan"

    @pytest.mark.asyncio
    async def test_plan_auto_corrects_on_validation_error(self, orchestrator):
        """When JSON is valid but fails Pydantic validation, should retry."""
        valid = (
            '{"summary": "Corrected", '
            '"files": [{"path": "c.py", "language": "python", '
            '"purpose": "Corrected", "dependencies": []}], '
            '"test_strategy": "pytest"}'
        )
        orchestrator.planner_llm.chat = AsyncMock(side_effect=[
            # Missing test_strategy — fails Pydantic validation
            '{"summary": "Bad", "files": []}',
            valid,
        ])

        result = await orchestrator._plan("Build something")

        assert result.success
        assert result.corrections == 1
        assert result.plan.summary == "Corrected"


# ── Generate-with-retry step tests ────────────────────────────────


class TestOrchestratorPipelineGenerate:
    """Tests for generate-with-retry pipeline step (unchanged from M5)."""

    @pytest.mark.asyncio
    async def test_generate_file_success_no_sandbox(self):
        orchestrator = Orchestrator()
        orchestrator.code_agent.execute = AsyncMock(return_value=mock_code_agent_success())

        from src.common.schemas import FileSpec
        file_spec = FileSpec(path="hello.py", language="python", purpose="Print hello world")
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
        orchestrator = Orchestrator(sandbox=mock_sandbox)
        orchestrator.code_agent.execute = AsyncMock(return_value=mock_code_agent_success())

        from src.common.schemas import FileSpec
        file_spec = FileSpec(path="hello.py", language="python", purpose="Print hello")
        result = await orchestrator._generate_file_with_retry(
            file_spec, "Test project", ["hello.py"],
        )

        assert result.success
        assert result.sandbox_tested
        assert result.sandbox_passed is True
        assert result.sandbox_output == "OK\n"
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_generate_file_heals_on_failure(self):
        sandbox = AsyncMock()
        sandbox.write_file = AsyncMock(return_value=True)
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
        orchestrator.code_agent.execute = AsyncMock(return_value=mock_code_agent_success(
            code="print('fixed')", file_path="/tmp/f.py"
        ))

        from src.common.schemas import FileSpec
        file_spec = FileSpec(path="fix.py", language="python", purpose="Fix test")
        result = await orchestrator._generate_file_with_retry(
            file_spec, "Test project", ["fix.py"],
        )

        assert result.success
        assert result.sandbox_tested
        assert result.sandbox_passed is True
        assert result.attempts == 3

    @pytest.mark.asyncio
    async def test_generate_file_exhausts_retries(self):
        sandbox = AsyncMock()
        sandbox.write_file = AsyncMock(return_value=True)
        sandbox.run_file = AsyncMock(return_value=SandboxResult(
            success=False, stderr="Always fails", stdout="", exit_code=1,
        ))

        orchestrator = Orchestrator(sandbox=sandbox)
        orchestrator.code_agent.execute = AsyncMock(return_value=mock_code_agent_success(
            code="bad code", file_path="/tmp/b.py"
        ))

        from src.common.schemas import FileSpec
        file_spec = FileSpec(path="bad.py", language="python", purpose="Bad file")
        result = await orchestrator._generate_file_with_retry(
            file_spec, "Test project", ["bad.py"],
        )

        assert not result.sandbox_passed
        assert result.sandbox_error == "Always fails"
        assert result.attempts == 3

    @pytest.mark.asyncio
    async def test_generation_failure(self):
        orchestrator = Orchestrator()
        orchestrator.code_agent.execute = AsyncMock(return_value={
            "success": False, "error": "LLM call failed",
        })

        from src.common.schemas import FileSpec
        file_spec = FileSpec(path="fail.py", language="python", purpose="Fails")
        result = await orchestrator._generate_file_with_retry(
            file_spec, "Test project", ["fail.py"],
        )

        assert not result.success
        assert "LLM call failed" in result.error
        assert result.attempts == 1


# ── Full pipeline integration tests ───────────────────────────────


class TestOrchestratorPipelineRun:
    """Integration tests for the full pipeline (all mocked)."""

    @pytest.mark.asyncio
    async def test_run_full_cycle_no_sandbox(self, valid_plan_json, tmp_path):
        orchestrator = Orchestrator()
        orchestrator.planner_llm.chat = AsyncMock(return_value=valid_plan_json)
        orchestrator.code_agent.llm.chat = AsyncMock(return_value="print('hello')")

        import os
        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        try:
            result = await orchestrator.run("Build hello world")

            assert isinstance(result, PipelineResult)
            assert result.success
            assert result.summary == "Build a todo API"
            assert len(result.files) == 1
            assert result.files[0].path == "app.py"
            assert result.files[0].success
            assert result.pipeline_test is None  # no sandbox
            assert result.total_attempts == 1
            assert result.corrections == 0
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio
    async def test_run_full_cycle_with_sandbox(self, mock_sandbox, valid_plan_json, tmp_path):
        orchestrator = Orchestrator(sandbox=mock_sandbox)
        orchestrator.planner_llm.chat = AsyncMock(return_value=(
            '{"summary": "Build a todo API", '
            '"files": [{"path": "app.py", "language": "python", '
            '"purpose": "Main API", "dependencies": []}, '
            '{"path": "tests/test_app.py", "language": "python", '
            '"purpose": "Test the API", "dependencies": ["app.py"]}], '
            '"test_strategy": "Run pytest tests/"}'
        ))
        orchestrator.code_agent.execute = AsyncMock(return_value=mock_code_agent_success(
            code="def foo(): pass", file_path=str(tmp_path / "test_file.py")
        ))

        result = await orchestrator.run("Build a todo API")

        assert result.success
        assert len(result.files) == 2
        assert result.pipeline_test is not None
        assert result.pipeline_test.success
        assert result.total_attempts == 2

    @pytest.mark.asyncio
    async def test_run_fails_on_bad_plan(self):
        orchestrator = Orchestrator()
        orchestrator.planner_llm.chat = AsyncMock(return_value="invalid json")

        result = await orchestrator.run("Build something")

        assert not result.success
        assert "failed" in result.error

    @pytest.mark.asyncio
    async def test_run_with_knowledge_base_stores_results(
        self, mock_sandbox, mock_kb, valid_plan_json, tmp_path
    ):
        orchestrator = Orchestrator(sandbox=mock_sandbox, knowledge_base=mock_kb)
        orchestrator.planner_llm.chat = AsyncMock(return_value=valid_plan_json)
        orchestrator.code_agent.execute = AsyncMock(return_value=mock_code_agent_success(
            code="print('hello')", file_path=str(tmp_path / "hello.py")
        ))

        result = await orchestrator.run("Write hello world")

        assert result.success
        assert result.kb_stored
        mock_kb.store.assert_called()

    @pytest.mark.asyncio
    async def test_run_healing_loop_with_sandbox(self, tmp_path):
        sandbox = AsyncMock()
        sandbox.write_file = AsyncMock(return_value=True)
        sandbox.read_file = AsyncMock(return_value="print('fixed')")
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
        orchestrator.code_agent.execute = AsyncMock(return_value=mock_code_agent_success(
            code="print('code')", file_path=str(tmp_path / "code.py")
        ))

        result = await orchestrator.run("Build app with tests")

        assert result.success
        assert len(result.files) == 2
        assert result.files[0].attempts == 1
        assert result.files[1].attempts == 3

    @pytest.mark.asyncio
    async def test_run_with_plan_correction(self, tmp_path):
        """Pipeline should work even when planning requires a correction."""
        valid = (
            '{"summary": "Fixed calculator", '
            '"files": [{"path": "calc.py", "language": "python", '
            '"purpose": "Calculator", "dependencies": []}], '
            '"test_strategy": "pytest"}'
        )
        orchestrator = Orchestrator()
        orchestrator.planner_llm.chat = AsyncMock(side_effect=[
            '{"summary": "broken"',  # invalid JSON
            valid,
        ])
        orchestrator.code_agent.execute = AsyncMock(return_value=mock_code_agent_success())

        import os
        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        try:
            result = await orchestrator.run("Build a calculator")
            assert result.success
            assert result.summary == "Fixed calculator"
            assert result.corrections == 1
        finally:
            os.chdir(original_cwd)


# ── Data class tests ──────────────────────────────────────────────


class TestPipelineFileResult:
    """Tests for PipelineFileResult Pydantic model."""

    def test_to_dict(self):
        r = PipelineFileResult(
            path="test.py", language="python", purpose="Testing",
            success=True, lines=10, file_path="/tmp/test.py",
            sandbox_tested=True, sandbox_passed=True,
            sandbox_output="OK", sandbox_error="", attempts=2,
        )
        d = r.to_dict()
        assert d["path"] == "test.py"
        assert d["success"] is True
        assert d["sandbox_passed"] is True
        assert d["attempts"] == 2

    def test_roundtrip_via_model_dump(self):
        r = PipelineFileResult(path="x.py", language="python", purpose="X")
        d = r.model_dump()
        r2 = PipelineFileResult(**d)
        assert r2.path == "x.py"
        assert r2.language == "python"


class TestPipelineResult:
    """Tests for PipelineResult Pydantic model."""

    def test_to_dict_no_test(self):
        r = PipelineResult(
            success=True, summary="Test", files=[],
            test_strategy="Run", total_duration=1.5, total_attempts=3,
        )
        d = r.to_dict()
        assert d["success"] is True
        assert d["total_duration"] == 1.5
        assert d["total_attempts"] == 3
        assert d["pipeline_test"] is None

    def test_to_dict_with_test(self):
        r = PipelineResult(
            success=True, summary="Test", files=[],
            pipeline_test=PipelineTestResult(success=True, stdout="OK"),
            total_duration=2.0, total_attempts=1,
        )
        d = r.to_dict()
        assert d["pipeline_test"]["success"] is True
        assert d["pipeline_test"]["stdout"] == "OK"

    def test_roundtrip_via_model_dump(self):
        r = PipelineResult(
            success=True, summary="Calc",
            files=[PipelineFileResult(path="calc.py", language="python", purpose="C")],
        )
        d = r.model_dump()
        r2 = PipelineResult(**d)
        assert r2.success
        assert r2.summary == "Calc"
        assert len(r2.files) == 1
