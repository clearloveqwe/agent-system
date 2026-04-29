# Agents Configuration for agent-system

This file defines agent behavior within this repository.

## General Principles

- **Think before coding** — state assumptions, surface tradeoffs
- **Simplicity first** — minimum code that solves the problem
- **Surgical changes** — touch only what you must
- **Goal-driven execution** — define success criteria, loop until verified

## Project Context

This is a multi-agent system for full-stack web application development.
Agents in this repo should:

1. Follow the execution spec (PLAN → RETRIEVE → EXECUTE → VERIFY → REPORT)
2. Log all key actions to `execution_log.md`
3. Create feature branches from `main`, submit PRs with descriptive titles
4. Write tests before or alongside implementation code
5. Use structured output (markdown tables, diffs, lists)

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
