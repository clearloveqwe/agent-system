"""Tests for discussion-style planning — plan_draft, plan_refine, run_with_plan."""

from unittest.mock import AsyncMock

import pytest

from src.orchestrator.orchestrator import Orchestrator
from src.common.schemas import PlanDraft, ProjectPlan, FileSpec, PipelineResult
from src.sandbox.base import SandboxResult


def _mock_discussion_response(plan_data: dict) -> str:
    """Build a JSON string that matches the discussion schema."""
    import json
    return json.dumps(plan_data)


@pytest.fixture
def orchestrator():
    return Orchestrator()


@pytest.fixture
def mock_sandbox():
    sb = AsyncMock()
    sb.write_file = AsyncMock(return_value=True)
    sb.read_file = AsyncMock(return_value="print('ok')")
    sb.run_file = AsyncMock(return_value=SandboxResult(True, stdout="OK\n"))
    sb.install_deps = AsyncMock(return_value=SandboxResult(True, stdout=""))
    sb.run_code = AsyncMock(return_value=SandboxResult(True, stdout="PASS\n"))
    return sb


class TestPlanDraft:
    """Tests for the PlanDraft model itself."""

    def test_present_draft(self):
        plan = ProjectPlan(
            summary="Todo app",
            files=[
                FileSpec(path="app.py", language="python", purpose="Main app"),
                FileSpec(path="tests/test_app.py", language="python", purpose="Tests"),
            ],
            test_strategy="pytest",
        )
        draft = PlanDraft(plan=plan, iteration=1)
        output = draft.present()
        assert "Architecture Draft (v1)" in output
        assert "app.py" in output
        assert "Todo app" in output
        assert "pytest" in output
        assert "confirm" in output

    def test_present_with_alternatives(self):
        main = ProjectPlan(summary="FastAPI", files=[FileSpec(path="main.py", language="python", purpose="API")], test_strategy="pytest")
        alt = ProjectPlan(summary="Django", files=[FileSpec(path="views.py", language="python", purpose="Views")], test_strategy="pytest")
        draft = PlanDraft(plan=main, alternatives=[alt])
        output = draft.present()
        assert "FastAPI" in output
        assert "Django" in output
        assert "Alternative Architectures" in output

    def test_present_with_discussion_history(self):
        plan = ProjectPlan(summary="Test", files=[FileSpec(path="x.py", language="python", purpose="X")], test_strategy="pytest")
        draft = PlanDraft(
            plan=plan,
            discussion=[
                {"role": "user", "content": "Add auth"},
                {"role": "assistant", "content": "Added auth module"},
            ],
        )
        output = draft.present()
        assert "Discussion History" in output
        assert "Add auth" in output

    def test_present_empty_alternatives(self):
        """No alternatives section when none provided."""
        plan = ProjectPlan(summary="Simple", files=[FileSpec(path="a.py", language="python", purpose="A")], test_strategy="pytest")
        draft = PlanDraft(plan=plan)
        output = draft.present()
        assert "Alternative Architectures" not in output

    def test_roundtrip_serialization(self):
        plan = ProjectPlan(summary="Calc", files=[FileSpec(path="calc.py", language="python", purpose="Calc")], test_strategy="pytest")
        draft = PlanDraft(plan=plan, iteration=2, confirmed=False)
        d = draft.model_dump()
        draft2 = PlanDraft(**d)
        assert draft2.plan.summary == "Calc"
        assert draft2.iteration == 2


class TestPlanDraftMethod:
    """Tests for Orchestrator.plan_draft()."""

    @pytest.mark.asyncio
    async def test_plan_draft_basic(self, orchestrator):
        """plan_draft() should return a PlanDraft with main plan and alternatives."""
        mock_response = _mock_discussion_response({
            "summary": "Calculator API",
            "files": [
                {"path": "calc.py", "language": "python", "purpose": "Calc logic"},
            ],
            "test_strategy": "pytest",
            "alternatives": [
                {
                    "summary": "CLI version",
                    "files": [{"path": "cli.py", "language": "python", "purpose": "CLI"}],
                    "test_strategy": "manual",
                },
            ],
        })
        orchestrator.discuss_llm.chat = AsyncMock(return_value=mock_response)

        draft = await orchestrator.plan_draft("Build a calculator")

        assert isinstance(draft, PlanDraft)
        assert draft.plan.summary == "Calculator API"
        assert len(draft.plan.files) == 1
        assert len(draft.alternatives) == 1
        assert draft.alternatives[0].summary == "CLI version"
        assert draft.iteration == 1
        assert not draft.confirmed
        assert len(draft.discussion) == 1  # Initial entry

    @pytest.mark.asyncio
    async def test_plan_draft_with_context(self, orchestrator):
        """Context should be passed to the LLM."""
        mock_response = _mock_discussion_response({
            "summary": "Auth service",
            "files": [{"path": "auth.py", "language": "python", "purpose": "Auth"}],
            "test_strategy": "pytest",
        })
        orchestrator.discuss_llm.chat = AsyncMock(return_value=mock_response)

        draft = await orchestrator.plan_draft(
            "Build auth", context="Must use JWT tokens"
        )
        assert draft.plan.summary == "Auth service"

    @pytest.mark.asyncio
    async def test_plan_draft_no_alternatives(self, orchestrator):
        """Should handle responses with no alternatives gracefully."""
        mock_response = _mock_discussion_response({
            "summary": "Minimal",
            "files": [{"path": "m.py", "language": "python", "purpose": "Min"}],
            "test_strategy": "pytest",
        })
        orchestrator.discuss_llm.chat = AsyncMock(return_value=mock_response)

        draft = await orchestrator.plan_draft("Minimal app")
        assert len(draft.alternatives) == 0


class TestPlanRefine:
    """Tests for Orchestrator.plan_refine()."""

    @pytest.fixture
    def initial_draft(self):
        plan = ProjectPlan(
            summary="Todo API",
            files=[FileSpec(path="app.py", language="python", purpose="API")],
            test_strategy="pytest",
        )
        return PlanDraft(plan=plan, iteration=1)

    @pytest.mark.asyncio
    async def test_plan_refine_with_feedback(self, orchestrator, initial_draft):
        """plan_refine() should produce updated draft with incremented iteration."""
        mock_response = _mock_discussion_response({
            "summary": "Todo API with SQLite",
            "files": [
                {"path": "app.py", "language": "python", "purpose": "API"},
                {"path": "db.py", "language": "python", "purpose": "SQLite storage"},
            ],
            "test_strategy": "pytest",
        })
        orchestrator.discuss_llm.chat = AsyncMock(return_value=mock_response)

        refined = await orchestrator.plan_refine(initial_draft, "Add SQLite storage")

        assert refined.plan.summary == "Todo API with SQLite"
        assert len(refined.plan.files) == 2
        assert refined.iteration == 2
        assert not refined.confirmed
        assert len(refined.discussion) == 2  # feedback + response

    @pytest.mark.asyncio
    async def test_plan_refine_preserves_history(self, orchestrator, initial_draft):
        """Discussion history should accumulate across refinements."""
        mock_response = _mock_discussion_response({
            "summary": "Todo API v2",
            "files": [{"path": "v2.py", "language": "python", "purpose": "V2"}],
            "test_strategy": "pytest",
        })
        orchestrator.discuss_llm.chat = AsyncMock(return_value=mock_response)

        # Two rounds of refinement
        v2 = await orchestrator.plan_refine(initial_draft, "Round 1")
        v3 = await orchestrator.plan_refine(v2, "Round 2")

        assert v3.iteration == 3
        assert len(v3.discussion) == 4  # 2 feedback + 2 responses
        assert v3.discussion[0]["content"] == "Round 1"
        assert v3.discussion[2]["content"] == "Round 2"


class TestRunWithPlan:
    """Tests for Orchestrator.run_with_plan()."""

    @pytest.mark.asyncio
    async def test_run_with_plan_executes_pipeline(self, mock_sandbox, tmp_path):
        """run_with_plan() should execute generation + sandbox testing."""
        orchestrator = Orchestrator(sandbox=mock_sandbox)
        orchestrator.code_agent.execute = AsyncMock(return_value={
            "success": True, "code": "print('ok')",
            "file_path": str(tmp_path / "app.py"), "language": "python", "lines": 1,
        })

        plan = ProjectPlan(
            summary="Test app",
            files=[FileSpec(path="app.py", language="python", purpose="App")],
            test_strategy="pytest",
        )

        result = await orchestrator.run_with_plan(plan)

        assert isinstance(result, PipelineResult)
        assert result.success
        assert result.summary == "Test app"
        assert result.total_attempts == 1

    @pytest.mark.asyncio
    async def test_run_with_plan_no_sandbox(self, tmp_path):
        """run_with_plan() works without sandbox — just generates files."""
        orchestrator = Orchestrator()
        orchestrator.code_agent.execute = AsyncMock(return_value={
            "success": True, "code": "print('ok')",
            "file_path": str(tmp_path / "test.py"), "language": "python", "lines": 1,
        })

        plan = ProjectPlan(
            summary="Simple",
            files=[FileSpec(path="hello.py", language="python", purpose="Hello")],
            test_strategy="manual",
        )

        result = await orchestrator.run_with_plan(plan)

        assert result.success
        assert result.pipeline_test is None  # no sandbox

    @pytest.mark.asyncio
    async def test_run_with_plan_with_kb(self, mock_sandbox, tmp_path):
        """run_with_plan() stores results in KB when configured."""
        kb = AsyncMock()
        kb.store = AsyncMock(return_value="entry-1")
        orchestrator = Orchestrator(sandbox=mock_sandbox, knowledge_base=kb)
        orchestrator.code_agent.execute = AsyncMock(return_value={
            "success": True, "code": "print('ok')",
            "file_path": str(tmp_path / "app.py"), "language": "python", "lines": 1,
        })

        plan = ProjectPlan(
            summary="Stored app",
            files=[FileSpec(path="app.py", language="python", purpose="App")],
            test_strategy="pytest",
        )

        result = await orchestrator.run_with_plan(plan)
        assert result.success
        assert result.kb_stored
        kb.store.assert_called()

    @pytest.mark.asyncio
    async def test_run_with_plan_healing(self, tmp_path):
        """run_with_plan() should still heal on sandbox failure."""
        sandbox = AsyncMock()
        sandbox.write_file = AsyncMock(return_value=True)
        sandbox.read_file = AsyncMock(return_value="print('fixed')")
        sandbox.run_file = AsyncMock(side_effect=[
            SandboxResult(success=False, stderr="Error: bad", exit_code=1),
            SandboxResult(success=True, stdout="OK", exit_code=0),
            SandboxResult(success=True, stdout="PASS", exit_code=0),  # pipeline test
        ])
        sandbox.install_deps = AsyncMock(return_value=SandboxResult(True))
        sandbox.run_code = AsyncMock(return_value=SandboxResult(True, stdout="PASS"))

        orchestrator = Orchestrator(sandbox=sandbox)
        orchestrator.code_agent.execute = AsyncMock(return_value={
            "success": True, "code": "print('code')",
            "file_path": str(tmp_path / "app.py"), "language": "python", "lines": 1,
        })

        plan = ProjectPlan(
            summary="Heal test",
            files=[FileSpec(path="app.py", language="python", purpose="App")],
            test_strategy="pytest",
        )

        result = await orchestrator.run_with_plan(plan)
        assert result.success
        assert result.files[0].attempts == 2  # healed on second attempt
