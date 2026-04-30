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

When a user asks to generate code for a project, follow this workflow:

**Step 1: Draft** — Call `orchestrator.plan_draft(requirement)` to generate initial
architecture draft with 1-2 alternatives. Show the user `draft.present()`.

**Step 2: Discuss** — Wait for user feedback. Call `orchestrator.plan_refine(draft, feedback)`
to update. Repeat until the user says "confirm" / "proceed" / "继续".

**Step 3: Execute** — Call `orchestrator.run_with_plan(draft.plan)` to generate code,
run sandbox tests, and store results.

Do NOT skip to code generation without a discussion cycle first. The discussion
ensures the user sees and approves the architecture before any code is written.

```python
# Example workflow
from src.orchestrator.orchestrator import Orchestrator

orc = Orchestrator()
draft = await orc.plan_draft("Build a todo API")
print(draft.present())
# User: "Add SQLite"
draft = await orc.plan_refine(draft, "Add SQLite")
# User: "confirm"
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
