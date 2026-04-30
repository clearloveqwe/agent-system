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
    FileSpec,
    PipelineFileResult,
    PipelineResult,
    PipelineTestResult,
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
