"""Tests for ClarifySession — multi-turn requirement clarification and handoff."""

from unittest.mock import AsyncMock

import pytest

from src.orchestrator.orchestrator import (
    ClarifySession,
    Orchestrator,
    validate_clarified_requirement,
)
from src.common.schemas import (
    ClarifiedRequirement,
    ClarifyResponse,
    FunctionalRequirement,
    NonFunctionalRequirement,
)


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def mock_llm():
    """A mock LLMClient that returns whatever we set."""
    llm = AsyncMock()
    return llm


@pytest.fixture
def session(mock_llm):
    """A ClarifySession with a mock LLM."""
    return ClarifySession(discuss_llm=mock_llm, config={"discuss_model": "test-model"})


def make_submit_response(**overrides) -> str:
    """Build a submit JSON string for ClarifyResponse."""
    import json

    base = {
        "action": "submit",
        "question": "",
        "summary_so_far": "Requirement clarified",
        "clarification": {
            "project_name": "Todo App",
            "project_goal": "A task management web application",
            "target_users": "Individual users",
            "functional_requirements": [
                {
                    "id": "FR-1",
                    "description": "Users can create tasks",
                    "user_story": "As a user, I want to create tasks",
                    "acceptance_criteria": ["Task is saved to database"],
                    "priority": "must",
                },
                {
                    "id": "FR-2",
                    "description": "Users can mark tasks complete",
                    "acceptance_criteria": ["Task status updates"],
                    "priority": "must",
                },
            ],
            "non_functional_requirements": [
                {"category": "performance", "description": "Page load < 2s"}
            ],
            "tech_stack_preference": {"frontend": "React", "backend": "FastAPI"},
            "constraints": "Must work offline",
            "confirmed_assumptions": ["PostgreSQL for storage"],
            "open_questions": ["Deployment target"],
        },
    }
    base.update(overrides)
    return json.dumps(base)


def make_ask_response(question: str = "What tech stack?") -> str:
    """Build an ask JSON string for ClarifyResponse."""
    import json

    return json.dumps({
        "action": "ask",
        "question": question,
        "summary_so_far": "Still gathering info",
        "clarification": None,
    })


# ── ClarifySession tests ─────────────────────────────────────────


class TestClarifySession:
    """Tests for the multi-turn clarification conversation."""

    @pytest.mark.asyncio
    async def test_ask_returns_question(self, session, mock_llm):
        """When discuss_llm needs more info, action='ask' with question."""
        mock_llm.chat = AsyncMock(return_value=make_ask_response("What is the project name?"))

        response = await session.ask()

        assert response.action == "ask"
        assert "project name" in response.question
        assert response.clarification is None
        assert len(session.turns) == 1  # assistant's turn recorded

    @pytest.mark.asyncio
    async def test_ask_returns_submit(self, session, mock_llm):
        """When discuss_llm has enough info, action='submit' with full clarification."""
        mock_llm.chat = AsyncMock(return_value=make_submit_response())

        response = await session.ask()

        assert response.action == "submit"
        assert response.clarification is not None
        assert response.clarification.project_name == "Todo App"
        assert len(response.clarification.functional_requirements) == 2
        assert response.clarification.functional_requirements[0].id == "FR-1"

    @pytest.mark.asyncio
    async def test_ask_with_current_state(self, session, mock_llm):
        """Can pass a partially filled ClarifiedRequirement as current state."""
        partial = ClarifiedRequirement(
            project_name="Partial App",
            project_goal="Test",
            functional_requirements=[],
        )
        mock_llm.chat = AsyncMock(return_value=make_ask_response("Add some features?"))

        response = await session.ask(current_state=partial)

        assert response.action == "ask"
        # The LLM should have been prompted with the partial state

    @pytest.mark.asyncio
    async def test_record_answer_appends_to_history(self, session):
        """record_answer() should add user turns to history."""
        session.record_answer("I want React")
        assert len(session.turns) == 1
        assert session.turns[0]["role"] == "user"
        assert session.turns[0]["content"] == "I want React"

    @pytest.mark.asyncio
    async def test_multi_turn_conversation(self, session, mock_llm):
        """Simulate a full multi-turn conversation: ask → answer → ask → answer → submit."""
        mock_llm.chat = AsyncMock(side_effect=[
            make_ask_response("What tech stack?"),
            make_ask_response("Any constraints?"),
            make_submit_response(),
        ])

        # Turn 1: ask → answer
        r1 = await session.ask()
        assert r1.action == "ask"
        session.record_answer("React and FastAPI")

        # Turn 2: ask → answer
        r2 = await session.ask()
        assert r2.action == "ask"
        session.record_answer("Must work offline")

        # Turn 3: submit
        r3 = await session.ask()
        assert r3.action == "submit"
        assert r3.clarification is not None

        assert len(session.turns) == 5  # 3 assistant + 2 user

    @pytest.mark.asyncio
    async def test_ask_with_state_includes_open_questions(self, session, mock_llm):
        """State with open questions should prompt LLM to continue asking."""
        state = ClarifiedRequirement(
            project_name="Test",
            project_goal="Test project",
            functional_requirements=[
                FunctionalRequirement(id="FR-1", description="Feature 1", priority="must"),
            ],
            open_questions=["Deployment target"],
        )
        mock_llm.chat = AsyncMock(return_value=make_ask_response("Where to deploy?"))

        response = await session.ask(current_state=state)
        assert response.action == "ask"
        # The prompt should include the open questions


# ── ClarifySession with turns test ──────────────────────────────


class TestClarifySessionAskWithTurns:
    """Tests that the ask method includes conversation history in the prompt."""

    @pytest.mark.asyncio
    async def test_turns_included_in_prompt(self, session, mock_llm):
        """After recording answers, the ask method should include turn history."""
        session.record_answer("I want a calculator")
        session.record_answer("Python CLI tool")

        mock_llm.chat = AsyncMock(return_value=make_submit_response())

        _ = await session.ask()

        # The mock should have been called with a prompt that includes both answers
        call_kwargs = mock_llm.chat.call_args
        messages = call_kwargs.kwargs["messages"]
        user_content = messages[-1]["content"]

        assert "calculator" in user_content
        assert "CLI" in user_content


# ── Validation tests ─────────────────────────────────────────────


class TestValidateClarifiedRequirement:
    """Tests for the validation layer."""

    def test_valid_requirement(self):
        req = ClarifiedRequirement(
            project_name="Todo App",
            project_goal="Manage tasks",
            functional_requirements=[
                FunctionalRequirement(id="FR-1", description="Create tasks", priority="must"),
            ],
        )
        valid, errors = validate_clarified_requirement(req)
        assert valid
        assert errors == []

    def test_missing_project_name(self):
        req = ClarifiedRequirement(
            project_name="",
            project_goal="Goal",
            functional_requirements=[
                FunctionalRequirement(id="FR-1", description="Feature", priority="must"),
            ],
        )
        valid, errors = validate_clarified_requirement(req)
        assert not valid
        assert any("project_name" in e for e in errors)

    def test_missing_goal(self):
        req = ClarifiedRequirement(
            project_name="Test",
            project_goal="",
            functional_requirements=[
                FunctionalRequirement(id="FR-1", description="Feature", priority="must"),
            ],
        )
        valid, errors = validate_clarified_requirement(req)
        assert not valid
        assert any("project_goal" in e for e in errors)

    def test_no_functional_requirements(self):
        req = ClarifiedRequirement(
            project_name="Test",
            project_goal="Goal",
            functional_requirements=[],
        )
        valid, errors = validate_clarified_requirement(req)
        assert not valid
        assert any("functional_requirement" in e for e in errors)

    def test_duplicate_ids(self):
        req = ClarifiedRequirement(
            project_name="Test",
            project_goal="Goal",
            functional_requirements=[
                FunctionalRequirement(id="FR-1", description="Feature A", priority="must"),
                FunctionalRequirement(id="FR-1", description="Feature B", priority="must"),
            ],
        )
        valid, errors = validate_clarified_requirement(req)
        assert not valid
        assert any("duplicate" in e for e in errors)

    def test_invalid_priority(self):
        req = ClarifiedRequirement(
            project_name="Test",
            project_goal="Goal",
            functional_requirements=[
                FunctionalRequirement(id="FR-1", description="Feature", priority="invalid"),
            ],
        )
        valid, errors = validate_clarified_requirement(req)
        assert not valid
        assert any("priority" in e for e in errors)


# ── plan_draft with ClarifiedRequirement tests ───────────────────


class TestPlanDraftWithClarified:
    """Tests for plan_draft() when receiving a ClarifiedRequirement."""

    @pytest.fixture
    def orchestrator(self):
        return Orchestrator()

    @pytest.fixture
    def sample_clarified(self):
        return ClarifiedRequirement(
            project_name="Todo App",
            project_goal="A task management app",
            target_users="Individual users",
            functional_requirements=[
                FunctionalRequirement(
                    id="FR-1",
                    description="Create and edit tasks",
                    user_story="As a user I want to create tasks",
                    acceptance_criteria=["Task saved to DB", "Task editable after creation"],
                    priority="must",
                ),
                FunctionalRequirement(
                    id="FR-2",
                    description="Mark tasks complete",
                    acceptance_criteria=["Task status changes"],
                    priority="must",
                ),
            ],
            non_functional_requirements=[
                NonFunctionalRequirement(category="performance", description="Page load < 2s"),
            ],
            tech_stack_preference={"frontend": "React", "backend": "FastAPI"},
            constraints="Must work offline",
            confirmed_assumptions=["PostgreSQL for persistence"],
            open_questions=["Deployment platform"],
        )

    @pytest.mark.asyncio
    async def test_plan_draft_with_clarified_req(self, orchestrator, sample_clarified):
        """plan_draft() should accept a ClarifiedRequirement and generate a plan."""
        mock_response = (
            '{"summary": "Todo App with FastAPI + React", '
            '"files": [{"path": "backend/main.py", "language": "python", '
            '"purpose": "FastAPI entry point", "dependencies": []}, '
            '{"path": "frontend/App.jsx", "language": "javascript", '
            '"purpose": "React main component", "dependencies": []}], '
            '"test_strategy": "pytest backend/ && npm test frontend/"}'
        )
        orchestrator.discuss_llm.chat = AsyncMock(return_value=mock_response)

        draft = await orchestrator.plan_draft(clarified_req=sample_clarified)

        assert draft.plan.summary == "Todo App with FastAPI + React"
        assert len(draft.plan.files) == 2

    @pytest.mark.asyncio
    async def test_plan_draft_with_clarified_has_context(self, orchestrator, sample_clarified):
        """The ClarifiedRequirement fields should be injected into the LLM prompt."""
        mock_response = (
            '{"summary": "Todo App plan", '
            '"files": [{"path": "app.py", "language": "python", '
            '"purpose": "App", "dependencies": []}], '
            '"test_strategy": "pytest"}'
        )
        orchestrator.discuss_llm.chat = AsyncMock(return_value=mock_response)

        _ = await orchestrator.plan_draft(clarified_req=sample_clarified)

        # Check that the prompt included the clarified requirement
        call_args = orchestrator.discuss_llm.chat.call_args
        messages = call_args.kwargs["messages"]
        user_content = messages[-1]["content"]

        assert "Todo App" in user_content
        assert "FR-1" in user_content
        assert "Create and edit tasks" in user_content
        assert "PostgreSQL" in user_content
        assert "Deployment" in user_content  # open questions
        assert "React" in user_content
        assert "FastAPI" in user_content

    @pytest.mark.asyncio
    async def test_plan_draft_requires_input(self, orchestrator):
        """plan_draft() should raise if neither requirement nor clarified_req given."""
        with pytest.raises(ValueError, match="Either requirement= or clarified_req="):
            await orchestrator.plan_draft()


# ── ClarifyResponse schema test ─────────────────────────────────


class TestClarifyResponse:
    """Tests for the ClarifyResponse Pydantic model."""

    def test_ask_response_valid(self):
        resp = ClarifyResponse(action="ask", question="What tech stack?")
        assert resp.action == "ask"
        assert resp.question == "What tech stack?"
        assert resp.clarification is None

    def test_submit_response_valid(self):
        req = ClarifiedRequirement(
            project_name="Test",
            project_goal="Goal",
            functional_requirements=[
                FunctionalRequirement(id="FR-1", description="Feature", priority="must"),
            ],
        )
        resp = ClarifyResponse(action="submit", clarification=req)
        assert resp.action == "submit"
        assert resp.clarification.project_name == "Test"

    def test_invalid_action_rejected(self):
        with pytest.raises(Exception):  # Pydantic validation error
            ClarifyResponse(action="invalid")

    def test_roundtrip_serialization(self):
        req = ClarifiedRequirement(
            project_name="App",
            project_goal="Goal",
            functional_requirements=[
                FunctionalRequirement(id="FR-1", description="Feature", priority="must"),
            ],
        )
        resp = ClarifyResponse(action="submit", clarification=req)
        d = resp.model_dump()
        resp2 = ClarifyResponse(**d)
        assert resp2.action == "submit"
        assert resp2.clarification.project_name == "App"
