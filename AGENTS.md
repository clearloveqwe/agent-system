# Agents Configuration for agent-system

This file defines agent behavior within this repository.

## General Principles

- **Think before coding** — state assumptions, surface tradeoffs
- **Simplicity first** — minimum code that solves the problem
- **Surgical changes** — touch only what you must
- **Goal-driven execution** — define success criteria, loop until verified

## Lint & Commit Workflow (RULE: enforce before every commit)

1. **Write code & tests** as normal
2. **Lint before commit** — run `ruff check src/ tests/` and fix all errors
   - Auto-fix: `ruff check --fix src/ tests/` (handles ~30% of issues)
   - `__init__.py` exports: always use `as` alias (`from .x import X as X`) or `# noqa: F401`
   - Remove unused imports immediately — don't leave "defensive imports" for later
   - Never commit with `ruff check` exit code != 0
3. **Test before commit** — `pytest` must pass (coverage ≥ 85%)
4. **Final sanity** — `ruff check . && pytest` to confirm both pass
5. **Commit & push** — only if both steps 2-4 pass

If CI catches a lint/test failure, treat it as a **process bug** — fix the local workflow, not just the symptom.

## Project Context

This is a multi-agent system for full-stack web application development.
Agents in this repo should:

1. Follow the execution spec (PLAN → RETRIEVE → EXECUTE → VERIFY → REPORT)
2. Log all key actions to `execution_log.md`
3. Create feature branches from `main`, submit PRs with descriptive titles
4. Write tests before or alongside implementation code
5. Use structured output (markdown tables, diffs, lists)

## Discussion-Style Planning (RULE: use for all user-facing code generation)

When a user asks to generate code for a project, follow this three-phase workflow:

**Phase 1: Clarify** — Before any architecture or code, clarify the requirement.
Use `ClarifySession` to conduct a multi-turn conversation:
1. Call `session.ask(current_state)` to get the LLM's next question or submission
2. If `action == "ask"`, show the question to the user, collect their answer,
   call `session.record_answer(answer)`, and repeat
3. If `action == "submit"`, you have a `ClarifiedRequirement` — validate it with
   `validate_clarified_requirement()` before passing to the planner

**Phase 2: Draft** — Call `orchestrator.plan_draft(clarified_req=req)` to generate
initial architecture draft with 1-2 alternatives. Show the user `draft.present()`.
If the user has feedback, call `orchestrator.plan_refine(draft, feedback)` to update.
Repeat until the user says "confirm" / "proceed" / "继续".

**Phase 3: Execute** — Call `orchestrator.run_with_plan(draft.plan)` to generate code,
run sandbox tests, heal on failure, and store results.

Do NOT skip to code generation without completing Phase 1 and Phase 2 first.
The discussion ensures the user sees and approves the architecture before any code is written.

```python
# Complete workflow
from src.orchestrator.orchestrator import Orchestrator, ClarifySession, validate_clarified_requirement
from src.common.llm_client import LLMClient
from src.common.schemas import ClarifiedRequirement

orc = Orchestrator()
llm = LLMClient()
session = ClarifySession(discuss_llm=llm)

# Phase 1: Clarify
state = ClarifiedRequirement(project_name="App", project_goal="...", functional_requirements=[])
while True:
    resp = await session.ask(current_state=state)
    if resp.action == "submit":
        clarified = resp.clarification
        valid, errors = validate_clarified_requirement(clarified)
        if not valid:
            # Handle validation errors
            pass
        break
    # Show question to user, get answer
    session.record_answer(user_answer)

# Phase 2: Draft + Discuss
draft = await orc.plan_draft(clarified_req=clarified)
print(draft.present())
# User feedback → refine
draft = await orc.plan_refine(draft, feedback)
# User: "confirm"

# Phase 3: Execute
result = await orc.run_with_plan(draft.plan)
```

## Directory Layout

- `src/orchestrator/` — Task decomposition, agent orchestration, workflow engine
- `src/agents/` — Individual agent implementations (frontend, backend, DB, QA)
- `src/sandbox/` — Sandbox abstraction layer (E2B, Docker)
- `src/common/` — Shared utilities, LLM client, logging
- `config/` — Agent configuration, prompts, policies
- `tests/` — Unit and integration tests

## Security

- No hardcoded API keys or secrets
- Run sandboxed code only through the sandbox layer
- High-risk operations (DB schema, auth, secrets) require human review
