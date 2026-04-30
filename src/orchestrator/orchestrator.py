"""Orchestrator — end-to-end pipeline: requirement → plan → generate → test → store → report.

Uses Pydantic schemas for structured output validation and auto-correction.
"""

import json
import os
import time
from typing import Optional

from pydantic import ValidationError

from src.agents.code_agent import CodeAgent
from src.common.llm_client import LLMClient
from src.common.knowledge_base import KnowledgeEntry
from src.common.knowledge_base import BaseKnowledgeBase
from src.common.schemas import (
    ClarifiedRequirement,
    ClarifyResponse,
    FileSpec,
    PipelineFileResult,
    PipelineResult,
    PipelineTestResult,
    PlanDraft,
    ProjectPlan,
)
from src.sandbox.base import Sandbox as Sandbox
from src.sandbox.base import SandboxResult as SandboxResult


PLANNER_PROMPT = """You are a senior software architect. Given a user requirement, produce a JSON plan.

Output ONLY valid JSON matching this schema:
{
  "summary": "Brief description of what needs to be built",
  "files": [
    {
      "path": "relative/file/path",
      "language": "python|javascript|typescript|html|css|sql",
      "purpose": "What this file does",
      "dependencies": ["other file paths this depends on"]
    }
  ],
  "test_strategy": "How to verify this works: include test file paths and commands"
}

Rules:
- Break the requirement into the minimum set of files needed
- Each file should have a single responsibility
- Include test files
- Use relative paths from the project root
- For Python projects, include a test file (tests/test_*.py)
- The test file should import and test the main module

IMPORTANT: Return ONLY valid JSON. No markdown fences, no explanations."""

HEAL_PROMPT = """You are an expert software engineer fixing code that failed testing.

Previous code:
```{language}
{code}
```

Test command: {test_command}

Test output (stderr):
{test_stderr}

Test output (stdout):
{test_stdout}

Task: Fix the code so all tests pass. Output ONLY the corrected code — no explanations, no markdown fences."""

DISCUSSION_PROMPT = """You are a senior software architect leading a design review session.

Your task: given a user requirement and optional feedback, propose a project architecture.

Output valid JSON matching this schema:
{
  "summary": "Brief description of what needs to be built",
  "files": [
    {
      "path": "relative/file/path",
      "language": "python|javascript|typescript|html|css|sql",
      "purpose": "What this file does",
      "dependencies": ["other file paths this depends on"]
    }
  ],
  "test_strategy": "How to verify this works",
  "alternatives": [
    {
      "summary": "Alternative approach description",
      "files": [... same structure ...],
      "test_strategy": "How to test this alternative"
    }
  ]
}

Rules for discussion:
- Propose ONE main architecture as "summary"/"files"
- Offer 1-2 alternative approaches in "alternatives" (keep them concise)
- If the user provided feedback, address it specifically
- Each file should have a single responsibility
- Include test files for Python/JS projects
- Use relative paths from the project root

IMPORTANT: Return ONLY valid JSON. No markdown fences, no explanations."""

CLARIFY_PROMPT = """You are a requirements analyst. Your job is to clarify a user's vague project idea into a structured specification.

You drive a multi-turn conversation. Your output is a JSON object with one of two actions:

### If you need more information (action="ask"):
{
  "action": "ask",
  "question": "Your one question here",
  "summary_so_far": "Brief summary of what you've gathered so far"
}

### If you have enough information (action="submit"):
{
  "action": "submit",
  "summary_so_far": "Summary of the clarified requirement",
  "clarification": { ... ClarifiedRequirement object ... }
}

Rules:
- Ask ONE question at a time. Never ask multiple questions in one turn.
- Be conversational, friendly, and specific.
- Cover these dimensions (not necessarily in this order):
  1. Project name and overall goal
  2. Core features (functional requirements)
  3. Target users
  4. Preferred tech stack
  5. Non-functional requirements (performance, security)
  6. Constraints (time, budget, deployment)
- You have the CURRENT clarification state below. Build on it, don't restart.
- When you have enough info -> submit. You MUST submit within 6 questions.
- Each question should target a field that is still empty or incomplete in the current state.
- For the clarification object, use realistic IDs like 'FR-1', 'FR-2' for functional requirements.
- If the user says they don't know or don't care about something, mark it as an explicit assumption."""


class ClarifySession:
    """Manages a multi-turn clarification conversation with the user.

    1. Call ask_question() to start or continue the conversation
    2. If it returns a question, present it to the user and await their answer
    3. Call record_answer(session, user_answer) with the user's response
    4. Repeat until ask_question() returns action='submit'
    5. Call submit_clarified(session) to get the final ClarifiedRequirement

    Usage (from the agent/chat layer):
        session = ClarifySession(discuss_llm, config)
        while True:
            response = await session.ask(history, current_state)
            if response.action == "submit":
                req = response.clarification
                break
            # Present response.question to user
            user_answer = await get_user_input()
            history.append(("user", user_answer))

    The session preserves all conversation turns for traceability.
    """

    MAX_TURNS = 10

    def __init__(self, discuss_llm: LLMClient, config: Optional[dict] = None):
        self.llm = discuss_llm
        self.config = config or {}
        self.turns: list[dict] = []  # Full conversation history for traceability

    async def ask(
        self,
        current_state: Optional[ClarifiedRequirement] = None,
    ) -> ClarifyResponse:
        """Send the current conversation state to discuss_llm and get the next response.

        Returns a ClarifyResponse with either a question (action='ask')
        or the final requirement (action='submit').
        """
        # Build messages: system prompt + current state + conversation history
        state_json = ""
        if current_state:
            state_json = current_state.model_dump_json(indent=2)

        state_prompt = ""
        if state_json:
            state_prompt = (
                f"\n\nHere is the CURRENT clarification state "
                f"(fields may be partially filled):\n{state_json}"
            )

        turn_summary = ""
        user_turns = 0
        if self.turns:
            lines = []
            for t in self.turns:
                role = "📋 Assistant" if t["role"] == "assistant" else "👤 User"
                content = t["content"][:300]
                lines.append(f"{role}: {content}")
                if t["role"] == "user":
                    user_turns += 1
            turn_summary = "\n\nConversation so far:\n" + "\n".join(lines[-8:])

        user_message = (
            f"Current state of requirements clarification."
            f"{state_prompt}"
            f"{turn_summary}"
            f"\n\n{'' if user_turns < self.MAX_TURNS else '⚠️  MAX QUESTIONS REACHED. You MUST submit the requirement now.'}"
            f"\n\nDecide: ask another question or submit the final requirement."
        )

        schema = ClarifyResponse.model_json_schema()
        response_format = {
            "type": "json_object",
        }

        plan_text = await self.llm.chat(
            messages=[
                {"role": "system", "content": CLARIFY_PROMPT + f"\n\nYou MUST respond with valid JSON matching this schema:\n{json.dumps(schema, indent=2)}"},
                {"role": "user", "content": user_message},
            ],
            model=self.config.get("discuss_model", "deepseek-v4-flash"),
            max_tokens=4096,
            reasoning_effort="max",
            response_format=response_format,
        )

        response = ClarifyResponse.model_validate_json(plan_text)

        # Hard cap: if user has answered MAX_TURNS questions, force submit
        user_turns_after = sum(1 for t in self.turns if t["role"] == "user")
        if response.action == "ask" and user_turns_after >= self.MAX_TURNS:
            # Build a minimal submit from current state
            response = ClarifyResponse(
                action="submit",
                summary_so_far="Max questions reached, submitting current understanding",
                clarification=current_state or ClarifiedRequirement(
                    project_name="Project",
                    project_goal=user_message[:200],
                    functional_requirements=[],
                ),
            )

        self.turns.append({"role": "assistant", "content": response.summary_so_far or response.question})
        return response

    def record_answer(self, answer: str):
        """Record the user's answer in the conversation history.

        Call this AFTER presenting the question to the user and getting their response.
        """
        self.turns.append({"role": "user", "content": answer})


def validate_clarified_requirement(req: ClarifiedRequirement) -> tuple[bool, list[str]]:
    """Validate a ClarifiedRequirement before handing it to planner_llm.

    Returns (is_valid, error_messages).
    """
    errors: list[str] = []

    if not req.project_name.strip():
        errors.append("project_name is required")
    if not req.project_goal.strip():
        errors.append("project_goal is required")
    if not req.functional_requirements:
        errors.append("at least one functional_requirement is required")

    # Check for duplicate IDs
    ids = [fr.id for fr in req.functional_requirements]
    if len(ids) != len(set(ids)):
        duplicates = [x for x in ids if ids.count(x) > 1]
        errors.append(f"duplicate functional requirement IDs: {set(duplicates)}")

    # Check priority values
    valid_priorities = {"must", "should", "could"}
    for fr in req.functional_requirements:
        if fr.priority not in valid_priorities:
            errors.append(f"invalid priority '{fr.priority}' for {fr.id}")

    return len(errors) == 0, errors


class Orchestrator:
    """End-to-end pipeline: requirement → plan → generate → test → store → report.

    Components:
    - LLMClient for planning and healing
    - CodeAgent for code generation
    - Sandbox for code execution and testing
    - KnowledgeBase for storing and retrieving experiences

    Structured output: planning uses Pydantic validation + auto-correction up to 2 retries.
    Stage 1 implementation — single Agent handles the full pipeline.
    """

    MAX_HEAL_RETRIES = 3
    MAX_CORRECTIONS = 2

    def __init__(
        self,
        config: Optional[dict] = None,
        sandbox: Optional[Sandbox] = None,
        knowledge_base: Optional[BaseKnowledgeBase] = None,
    ):
        self.config = config or {}
        self.sandbox = sandbox
        self.kb = knowledge_base
        self.planner_llm = LLMClient(self.config.get("planner", {}))
        self.discuss_llm = LLMClient(self.config.get("discuss", {}) or self.config.get("planner", {}))
        self.healer_llm = LLMClient(self.config.get("healer", {}))
        self.code_agent = CodeAgent(
            model_config=self.config.get("code_agent", {}),
            knowledge_base=knowledge_base,
        )

    async def run(self, requirement: str) -> PipelineResult:
        """Execute a full end-to-end pipeline from a natural language requirement.

        Pipeline steps:
        1. Plan — decompose requirement into files (Pydantic-validated)
        2. Generate + Sandbox Test — generate each file, write to sandbox, run tests
        3. Heal — retry failed files with error context (up to MAX_HEAL_RETRIES)
        4. Pipeline Test — run full test suite in sandbox
        5. Store — store successful result in knowledge base
        6. Report — return structured result
        """
        start_time = time.time()
        total_attempts = 0
        total_corrections = 0

        # Step 1: Plan (Pydantic-validated with auto-correction)
        plan_result = await self._plan(requirement)
        if not plan_result.success:
            return PipelineResult(
                success=False,
                error=plan_result.error,
                total_duration=time.time() - start_time,
            )

        plan = plan_result.plan
        files_plan = plan.files
        summary = plan.summary
        test_strategy = plan.test_strategy
        total_corrections = plan_result.corrections

        # Step 2 & 3: Generate + Sandbox Test + Heal
        pipeline_files: list[PipelineFileResult] = []
        all_generation_success = True

        for file_spec in files_plan:
            file_result = await self._generate_file_with_retry(
                file_spec=file_spec,
                project_summary=summary,
                all_file_paths=[f.path for f in files_plan],
            )
            total_attempts += file_result.attempts
            pipeline_files.append(file_result)

            if not file_result.success:
                all_generation_success = False

        # Step 4: Run full test suite in sandbox
        pipeline_test_result: Optional[SandboxResult] = None
        if self.sandbox and all_generation_success:
            pipeline_test_result = await self._run_pipeline_tests(
                files_plan=[f.model_dump() for f in files_plan],
                test_strategy=test_strategy,
            )

        # Step 5: Store in knowledge base
        kb_stored = False
        if self.kb and all_generation_success:
            kb_stored = await self._store_pipeline_result(
                requirement=requirement,
                summary=summary,
                files=pipeline_files,
                test_strategy=test_strategy,
            )

        # Step 6: Report
        overall_success = all_generation_success
        if pipeline_test_result is not None:
            overall_success = overall_success and pipeline_test_result.success

        ptest = None
        if pipeline_test_result:
            ptest = PipelineTestResult(
                success=pipeline_test_result.success,
                stdout=pipeline_test_result.stdout,
                stderr=pipeline_test_result.stderr,
            )

        return PipelineResult(
            success=overall_success,
            summary=summary,
            files=pipeline_files,
            test_strategy=test_strategy,
            pipeline_test=ptest,
            kb_stored=kb_stored,
            total_duration=time.time() - start_time,
            total_attempts=total_attempts,
            corrections=total_corrections,
        )

    # ── Discussion-style Planning ─────────────────────────────────

    async def plan_draft(
        self,
        requirement: Optional[str] = None,
        context: Optional[str] = None,
        clarified_req: Optional[ClarifiedRequirement] = None,
    ) -> PlanDraft:
        """Generate an initial architecture draft for user discussion.

        Two input modes:
        1. Plain text: pass requirement=str (natural language)
        2. Structured: pass clarified_req=ClarifiedRequirement (from ClarifySession)

        Produces a main proposal + 1-2 alternatives.
        The draft can be displayed via `.present()` for user review.
        """
        messages = [
            {"role": "system", "content": DISCUSSION_PROMPT},
        ]

        if clarified_req:
            # Structured handoff from discuss_llm → planner
            req_text = (
                f"## Clarified Requirement\n\n"
                f"**Project:** {clarified_req.project_name}\n"
                f"**Goal:** {clarified_req.project_goal}\n"
                f"**Target Users:** {clarified_req.target_users or 'Not specified'}\n\n"
                f"### Functional Requirements\n"
            )
            for fr in clarified_req.functional_requirements:
                req_text += f"- [{fr.priority.upper()}] {fr.id}: {fr.description}\n"
                if fr.acceptance_criteria:
                    for ac in fr.acceptance_criteria:
                        req_text += f"  - AC: {ac}\n"

            if clarified_req.non_functional_requirements:
                req_text += "\n### Non-Functional Requirements\n"
                for nfr in clarified_req.non_functional_requirements:
                    target = f" → {nfr.target_value}" if nfr.target_value else ""
                    req_text += f"- {nfr.category}: {nfr.description}{target}\n"

            if clarified_req.tech_stack_preference:
                stack = ", ".join(f"{k}={v}" for k, v in clarified_req.tech_stack_preference.items())
                req_text += f"\n**Tech Stack:** {stack}\n"

            if clarified_req.constraints:
                req_text += f"\n**Constraints:** {clarified_req.constraints}\n"

            if clarified_req.confirmed_assumptions:
                req_text += "\n### Confirmed Assumptions\n"
                for a in clarified_req.confirmed_assumptions:
                    req_text += f"- {a}\n"

            if clarified_req.open_questions:
                req_text += "\n### ⚠️ Open Questions (unresolved risks)\n"
                for q in clarified_req.open_questions:
                    req_text += f"- {q}\n"

            messages.append({"role": "user", "content": req_text})
        elif requirement:
            messages.append({"role": "user", "content": requirement})
        else:
            raise ValueError("Either requirement= or clarified_req= must be provided")

        if context:
            messages.append({"role": "user", "content": f"Context:\n{context}"})

        plan_text = await self.discuss_llm.chat(
            messages=messages,
            model=self.config.get("planner_model", "deepseek-v4-flash"),
            max_tokens=3072,
            reasoning_effort="max",
            response_format=self._plan_schema(),
        )

        data = json.loads(plan_text)
        plan = ProjectPlan(**data)
        alternatives = [ProjectPlan(**a) for a in data.get("alternatives", [])]

        return PlanDraft(
            plan=plan,
            alternatives=alternatives,
            discussion=[{"role": "assistant", "content": f"Draft: {plan.summary}"}],
            iteration=1,
        )

    async def plan_refine(
        self,
        draft: PlanDraft,
        feedback: str,
    ) -> PlanDraft:
        """Refine an existing draft based on user feedback.

        The LLM receives the current plan + user feedback and produces
        an updated proposal. Discussion history is preserved.
        """
        # Build a context-rich prompt with the current plan and history
        current_plan_str = draft.plan.model_dump_json(indent=2)
        prompt = (
            f"User requirement (original): {draft.plan.summary}\n\n"
            f"Current architecture plan:\n{current_plan_str}\n\n"
            f"User feedback: {feedback}\n\n"
            f"Please revise the architecture to address this feedback. "
            f"Output the updated plan in JSON format."
        )

        discussion_entry = {"role": "user", "content": feedback}

        messages = [
            {"role": "system", "content": DISCUSSION_PROMPT},
            {"role": "user", "content": prompt},
        ]

        plan_text = await self.discuss_llm.chat(
            messages=messages,
            model=self.config.get("planner_model", "deepseek-v4-flash"),
            max_tokens=3072,
            reasoning_effort="max",
            response_format=self._plan_schema(),
        )

        data = json.loads(plan_text)
        plan = ProjectPlan(**data)
        alternatives = [ProjectPlan(**a) for a in data.get("alternatives", [])]

        history = list(draft.discussion)
        history.append(discussion_entry)
        history.append({"role": "assistant", "content": f"Revised: {plan.summary}"})

        return PlanDraft(
            plan=plan,
            alternatives=alternatives,
            discussion=history,
            confirmed=False,
            iteration=draft.iteration + 1,
        )

    async def run_with_plan(
        self,
        plan: ProjectPlan,
        requirement: Optional[str] = None,
    ) -> PipelineResult:
        """Execute the full pipeline with a pre-confirmed plan.

        Skips the planning step and goes directly to code generation.
        This is the entry point after the user confirms a PlanDraft.
        """
        start_time = time.time()
        total_attempts = 0

        files_plan = plan.files
        summary = plan.summary
        test_strategy = plan.test_strategy

        # Generate + Sandbox Test + Heal
        pipeline_files: list[PipelineFileResult] = []
        all_generation_success = True

        for file_spec in files_plan:
            file_result = await self._generate_file_with_retry(
                file_spec=file_spec,
                project_summary=summary,
                all_file_paths=[f.path for f in files_plan],
            )
            total_attempts += file_result.attempts
            pipeline_files.append(file_result)
            if not file_result.success:
                all_generation_success = False

        # Pipeline Test
        pipeline_test_result: Optional[SandboxResult] = None
        if self.sandbox and all_generation_success:
            pipeline_test_result = await self._run_pipeline_tests(
                files_plan=[f.model_dump() for f in files_plan],
                test_strategy=test_strategy,
            )

        # KB Store
        kb_stored = False
        if self.kb and all_generation_success:
            kb_stored = await self._store_pipeline_result(
                requirement=requirement or summary,
                summary=summary,
                files=pipeline_files,
                test_strategy=test_strategy,
            )

        overall_success = all_generation_success
        if pipeline_test_result is not None:
            overall_success = overall_success and pipeline_test_result.success

        ptest = None
        if pipeline_test_result:
            ptest = PipelineTestResult(
                success=pipeline_test_result.success,
                stdout=pipeline_test_result.stdout,
                stderr=pipeline_test_result.stderr,
            )

        return PipelineResult(
            success=overall_success,
            summary=summary,
            files=pipeline_files,
            test_strategy=test_strategy,
            pipeline_test=ptest,
            kb_stored=kb_stored,
            total_duration=time.time() - start_time,
            total_attempts=total_attempts,
        )

    def _plan_schema(self) -> dict:
        """Generate the JSON Schema dict for LLM response_format."""
        schema = ProjectPlan.model_json_schema()
        # Add alternatives to the schema
        alt_schema = ProjectPlan.model_json_schema()
        schema["properties"]["alternatives"] = {
            "type": "array",
            "items": alt_schema,
            "description": "Alternative approaches",
        }
        return {
            "type": "json_schema",
            "json_schema": {"name": "DiscussionPlan", "schema": schema},
        }

    async def _generate_file_with_retry(
        self,
        file_spec: FileSpec,
        project_summary: str,
        all_file_paths: list[str],
    ) -> PipelineFileResult:
        """Generate a file and optionally test it in sandbox, with retry on failure.

        Retries up to MAX_HEAL_RETRIES times, feeding sandbox errors back to the LLM.
        """
        path = file_spec.path
        language = file_spec.language
        purpose = file_spec.purpose
        dependencies = file_spec.dependencies

        last_code = ""
        last_error = ""
        last_stdout = ""

        for attempt in range(1, self.MAX_HEAL_RETRIES + 1):
            # Build context with previous error if healing
            heal_context = {}
            if attempt > 1 and last_error:
                heal_context["previous_error"] = (
                    f"Previous attempt failed with:\n"
                    f"STDERR:\n{last_error}\n"
                    f"STDOUT:\n{last_stdout}\n"
                    f"Fix the code and try again."
                )

            # Generate code
            gen_result = await self.code_agent.execute({
                "requirement": purpose,
                "language": language,
                "target_path": path,
                "context": {
                    "project_summary": project_summary,
                    "all_files": all_file_paths,
                    "dependencies": dependencies,
                    **heal_context,
                },
            })

            if not gen_result.get("success"):
                # Generation failure (API error, etc.) — fail fast, don't retry
                return PipelineFileResult(
                    path=path,
                    language=language,
                    purpose=purpose,
                    success=False,
                    error=gen_result.get("error", "Generation failed"),
                    attempts=attempt,
                )

            last_code = gen_result.get("code", "")

            # Write to sandbox and test
            if self.sandbox:
                sandbox_ok = await self.sandbox.write_file(path, last_code)
                if not sandbox_ok:
                    if attempt == self.MAX_HEAL_RETRIES:
                        return PipelineFileResult(
                            path=path,
                            language=language,
                            purpose=purpose,
                            success=False,
                            file_path=gen_result.get("file_path"),
                            lines=len(last_code.splitlines()),
                            sandbox_tested=True,
                            sandbox_passed=False,
                            sandbox_error="Failed to write file to sandbox",
                            attempts=attempt,
                        )
                    continue

                # Run the file in sandbox to check it compiles/runs
                test_result = await self._run_single_file_test(path, language)

                last_error = test_result.stderr or ""
                last_stdout = test_result.stdout or ""

                if test_result.success:
                    return PipelineFileResult(
                        path=path,
                        language=language,
                        purpose=purpose,
                        success=True,
                        file_path=gen_result.get("file_path"),
                        lines=len(last_code.splitlines()),
                        sandbox_tested=True,
                        sandbox_passed=True,
                        sandbox_output=test_result.stdout,
                        attempts=attempt,
                    )
            else:
                # No sandbox — just return the generated code
                return PipelineFileResult(
                    path=path,
                    language=language,
                    purpose=purpose,
                    success=True,
                    file_path=gen_result.get("file_path"),
                    lines=len(last_code.splitlines()),
                    sandbox_tested=False,
                    attempts=attempt,
                )

        # All retries exhausted
        return PipelineFileResult(
            path=path,
            language=language,
            purpose=purpose,
            success=True,  # code was generated but sandbox test failed
            file_path=gen_result.get("file_path"),
            lines=len(last_code.splitlines()),
            sandbox_tested=True,
            sandbox_passed=False,
            sandbox_output=last_stdout,
            sandbox_error=last_error,
            attempts=self.MAX_HEAL_RETRIES,
            error=f"Sandbox test failed after {self.MAX_HEAL_RETRIES} attempts",
        )

    async def _run_single_file_test(
        self, path: str, language: str
    ) -> SandboxResult:
        """Run a single file in the sandbox to verify it compiles/executes."""
        if language == "python":
            return await self.sandbox.run_file(path, language="python")
        elif language in ("javascript", "typescript"):
            return await self.sandbox.run_file(path, language="javascript")
        elif language in ("html", "css"):
            content = await self.sandbox.read_file(path)
            if content is not None:
                return SandboxResult(success=True, stdout="File exists and is readable")
            return SandboxResult(
                success=False, stderr="File not found in sandbox"
            )
        else:
            return SandboxResult(success=True, stdout=f"No test for {language} files")

    async def _run_pipeline_tests(
        self, files_plan: list[dict], test_strategy: str
    ) -> Optional[SandboxResult]:
        """Run the full test suite in sandbox after all files are written."""
        test_files = [f for f in files_plan if f.get("path", "").startswith("tests/")]
        main_files = [f for f in files_plan if not f.get("path", "").startswith("tests/")]

        if not test_files:
            for f in main_files:
                if f.get("language") == "python":
                    result = await self.sandbox.run_file(f["path"], language="python")
                    if not result.success and result.stderr:
                        if "Error" in result.stderr or "Traceback" in result.stderr:
                            return result

        for tf in test_files:
            if tf.get("language") == "python":
                result = await self.sandbox.run_file(tf["path"], language="python")
                if not result.success:
                    return result

        try:
            result = await self.sandbox.install_deps(["pytest"])
            if result.success:
                test_code = (
                    "import subprocess, sys; "
                    "r = subprocess.run([sys.executable, '-m', 'pytest', 'tests/', '-v'], "
                    "capture_output=True, text=True, timeout=30); "
                    "print(r.stdout); print(r.stderr, file=sys.stderr); "
                    "sys.exit(r.returncode)"
                )
                result = await self.sandbox.run_code(test_code, language="python")
                return result
        except Exception as e:
            return SandboxResult(
                success=False,
                stderr=f"Pipeline test execution failed: {e}",
            )

        return SandboxResult(
            success=True,
            stdout="No test files found or no applicable test runner",
        )

    async def _store_pipeline_result(
        self,
        requirement: str,
        summary: str,
        files: list[PipelineFileResult],
        test_strategy: str,
    ) -> bool:
        """Store the pipeline result in the knowledge base."""
        try:
            successful_files = [f for f in files if f.success]
            if not successful_files:
                return False

            for f in successful_files:
                code = ""
                if f.file_path and os.path.exists(f.file_path):
                    with open(f.file_path) as fh:
                        code = fh.read()
                elif self.sandbox:
                    code = await self.sandbox.read_file(f.path) or ""

                if code:
                    entry = KnowledgeEntry(
                        requirement=f"{requirement} — {f.purpose}",
                        solution=code,
                        language=f.language,
                        entry_type="code_gen",
                        metadata={
                            "summary": summary,
                            "path": f.path,
                            "sandbox_passed": f.sandbox_passed,
                            "test_strategy": test_strategy,
                        },
                    )
                    await self.kb.store(entry)

            return True
        except Exception:
            return False

    async def _plan(self, requirement: str) -> "_PlanResult":
        """Decompose a requirement into a validated ProjectPlan.

        Uses Pydantic model + JSON Schema for structured output.
        Auto-corrects on ValidationError up to MAX_CORRECTIONS times.
        """
        corrections = 0
        last_error = ""

        # Generate the JSON schema from the Pydantic model
        schema = ProjectPlan.model_json_schema()
        response_format = {"type": "json_schema", "json_schema": {"name": "ProjectPlan", "schema": schema}}

        for attempt in range(self.MAX_CORRECTIONS + 1):
            try:
                messages = [
                    {"role": "system", "content": PLANNER_PROMPT},
                    {"role": "user", "content": requirement},
                ]

                # Append correction context if retrying
                if attempt > 0 and last_error:
                    messages.append({
                        "role": "assistant",
                        "content": "That previous response failed validation.",
                    })
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Your previous response failed JSON schema validation. "
                            f"Fix the JSON output to match the required schema. "
                            f"Validation error:\n{last_error}\n\n"
                            f"Return ONLY valid JSON matching the schema."
                        ),
                    })

                plan_text = await self.planner_llm.chat(
                    messages=messages,
                    model=self.config.get("planner_model", "deepseek-v4-flash"),
                    max_tokens=2048,
                    reasoning_effort="max",
                    response_format=response_format,
                )

                # Try Pydantic validation first
                try:
                    plan = ProjectPlan.model_validate_json(plan_text)
                    return _PlanResult(success=True, plan=plan, corrections=corrections)
                except ValidationError as e:
                    corrections += 1
                    last_error = str(e)
                    if attempt >= self.MAX_CORRECTIONS:
                        # Fallback: try json.loads + manual dict check
                        try:
                            data = json.loads(plan_text)
                            plan = ProjectPlan(**data)
                            return _PlanResult(success=True, plan=plan, corrections=corrections)
                        except (json.JSONDecodeError, ValidationError) as fallback_err:
                            return _PlanResult(
                                success=False,
                                error=f"Plan validation failed after {self.MAX_CORRECTIONS + 1} attempts: {fallback_err}",
                                corrections=corrections,
                            )
                    continue

            except json.JSONDecodeError as e:
                # If LLM returned non-JSON at all, try to extract JSON
                corrections += 1
                last_error = str(e)
                if attempt >= self.MAX_CORRECTIONS:
                    return _PlanResult(
                        success=False,
                        error=f"Plan parsing failed after {self.MAX_CORRECTIONS + 1} attempts: {e}",
                        corrections=corrections,
                    )
                continue

        return _PlanResult(
            success=False,
            error="Planning failed: exhausted all attempts",
            corrections=corrections,
        )


class _PlanResult:
    """Internal result from the planning step."""

    def __init__(
        self,
        success: bool,
        plan: Optional[ProjectPlan] = None,
        error: str = "",
        corrections: int = 0,
    ):
        self.success = success
        self.plan = plan
        self.error = error
        self.corrections = corrections
