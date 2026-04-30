"""Integration test: real ClarifySession multi-turn conversation.

Tests the full clarify → handoff pipeline with real DeepSeek LLM calls.
This is a smoke test — not in pytest suite because it makes real API calls.
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.strip()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.orchestrator.orchestrator import ClarifySession, Orchestrator, validate_clarified_requirement
from src.common.llm_client import LLMClient
from src.common.schemas import ClarifiedRequirement, FunctionalRequirement, NonFunctionalRequirement


async def main():
    print("=" * 60)
    print("🧪 ClarifySession — Real LLM Integration Test")
    print("=" * 60)

    llm = LLMClient()
    session = ClarifySession(discuss_llm=llm, config={
        "discuss_model": "deepseek-chat",
    })

    print("\n📝 User requirement: 'Build a habit tracker'")
    print("-" * 60)

    # Build state incrementally from user answers
    state = ClarifiedRequirement(
        project_name="Habit Tracker",
        project_goal="Build a habit tracker app",
        functional_requirements=[],
    )

    user_answers = [
        ("project_goal", "A habit tracker app — users can log daily habits and see streaks"),
        ("target_users", "Individual users, mobile-first web app"),
        ("tech_stack", "React frontend, Python backend, SQLite for simplicity"),
        ("features", "Notifications for missed habits, data export"),
        ("constraints", "No specific deadline, just a working prototype"),
    ]

    async def update_state(key: str, value: str):
        nonlocal state
        if key == "project_goal":
            state.project_goal = value
        elif key == "target_users":
            state.target_users = value
        elif key == "tech_stack":
            state.tech_stack_preference = {"frontend": "React", "backend": "Python"}
            if "SQLite" in value:
                state.confirmed_assumptions.append("Using SQLite for storage")
        elif key == "features":
            state.functional_requirements = [
                FunctionalRequirement(id="FR-1", description="Log daily habits", priority="must"),
                FunctionalRequirement(id="FR-2", description="View streak history", priority="must"),
                FunctionalRequirement(id="FR-3", description="Notification for missed habits", priority="should",
                    acceptance_criteria=["User gets notified when a habit is missed"]),
                FunctionalRequirement(id="FR-4", description="Export habit data", priority="could",
                    acceptance_criteria=["Export to CSV format"]),
            ]
        elif key == "constraints":
            state.constraints = value

    turn = 0
    answer_idx = 0

    while turn < 10:
        turn += 1
        print(f"\n--- Turn {turn} ---")
        print(f"📤 Sending to discuss_llm (DeepSeek V4 Flash)...")

        response = await session.ask(current_state=state)

        if response.action == "submit":
            print(f"\n✅ discuss_llm submitted the final requirement!")
            req = response.clarification
            print(f"\n📋 CLARIFIED REQUIREMENT:")
            print(f"   Project:    {req.project_name}")
            print(f"   Goal:       {req.project_goal}")
            print(f"   Users:      {req.target_users}")
            print(f"   Tech Stack: {req.tech_stack_preference}")

            if req.functional_requirements:
                print(f"\n   Functional Requirements:")
                for fr in req.functional_requirements:
                    ac = f" [ACs: {len(fr.acceptance_criteria)}]" if fr.acceptance_criteria else ""
                    print(f"   • [{fr.priority.upper()}] {fr.id}: {fr.description}{ac}")

            if req.non_functional_requirements:
                print(f"\n   Non-Functional:")
                for nfr in req.non_functional_requirements:
                    t = f" → {nfr.target_value}" if nfr.target_value else ""
                    print(f"   • {nfr.category}: {nfr.description}{t}")

            if req.constraints:
                print(f"\n   Constraints: {req.constraints}")

            if req.confirmed_assumptions:
                print(f"\n   Confirmed Assumptions:")
                for a in req.confirmed_assumptions:
                    print(f"   • {a}")

            if req.open_questions:
                print(f"\n   ⚠️  Risks:")
                for q in req.open_questions:
                    print(f"   • {q}")

            # Validate
            valid, errors = validate_clarified_requirement(req)
            print(f"\n🔍 Validation: {'✅ PASS' if valid else '❌ FAIL'}")
            if errors:
                for e in errors:
                    print(f"   ❌ {e}")

            state = req
            break

        elif response.action == "ask":
            print(f"❓ discuss_llm: {response.question[:200]}")

            if answer_idx < len(user_answers):
                key, value = user_answers[answer_idx]
                answer_idx += 1
                print(f"💬 User:       {value[:200]}")
                await update_state(key, value)
                session.record_answer(value)
                print(f"   📦 State updated: {len(state.functional_requirements)} FRs, "
                      f"tech_stack={'yes' if state.tech_stack_preference else 'no'}, "
                      f"assumptions={len(state.confirmed_assumptions)}")
            else:
                print(f"💬 User: No more info — proceed with what you have")
                session.record_answer("No more to add, please submit with current info")

    print("\n" + "=" * 60)
    print(f"📊 Stats: {turn} turns, {answer_idx} answers given")
    print(f"   Session turns stored: {len(session.turns)}")

    # Handoff to plan_draft
    if state and state.functional_requirements:
        print(f"\n🔗 Handoff to planner_llm via plan_draft()...")
        orchestrator = Orchestrator()

        mock_plan = (
            '{"summary": "Habit tracker with React + Python", '
            '"files": [{"path": "backend/main.py", "language": "python", '
            '"purpose": "FastAPI entry point with habit CRUD", "dependencies": []}, '
            '{"path": "backend/models.py", "language": "python", '
            '"purpose": "SQLite models", "dependencies": []}, '
            '{"path": "frontend/src/App.jsx", "language": "javascript", '
            '"purpose": "React app with habit list", "dependencies": []}, '
            '{"path": "tests/test_api.py", "language": "python", '
            '"purpose": "pytest tests", "dependencies": ["backend/main.py"]}], '
            '"test_strategy": "pytest backend/"}'
        )
        orchestrator.discuss_llm.chat = AsyncMock(return_value=mock_plan)

        draft = await orchestrator.plan_draft(clarified_req=state)

        print(f"\n📋 PlanDraft from ClarifiedRequirement:")
        print(f"   Summary: {draft.plan.summary}")
        for f in draft.plan.files:
            print(f"   • {f.path} — {f.purpose}")
        print(f"   Test: {draft.plan.test_strategy}")
        print(f"\n✅ Handoff: ClarifiedRequirement → ProjectPlan ✓")
    else:
        print(f"\n⚠️  No clarification submitted")

    print("\n" + "=" * 60)
    print("✅ Integration test complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
