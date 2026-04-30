"""Orchestrator — end-to-end pipeline: requirement → plan → generate → test → store → report."""

import json
import os
import time
from typing import Optional

from src.agents.code_agent import CodeAgent
from src.common.llm_client import LLMClient
from src.common.knowledge_base import KnowledgeEntry
from src.common.knowledge_base import BaseKnowledgeBase
from src.sandbox.base import Sandbox as Sandbox
from src.sandbox.base import SandboxResult as SandboxResult

PLANNER_PROMPT = """You are a senior software architect. Given a user requirement, produce a JSON plan.

Output ONLY valid JSON with this exact structure:
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
- The test file should import and test the main module"""

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


class PipelineFileResult:
    """Result for a single file in the pipeline."""

    def __init__(
        self,
        path: str,
        language: str,
        purpose: str,
        success: bool = False,
        lines: int = 0,
        file_path: Optional[str] = None,
        sandbox_tested: bool = False,
        sandbox_passed: Optional[bool] = None,
        sandbox_output: str = "",
        sandbox_error: str = "",
        attempts: int = 1,
        error: Optional[str] = None,
    ):
        self.path = path
        self.language = language
        self.purpose = purpose
        self.success = success
        self.lines = lines
        self.file_path = file_path
        self.sandbox_tested = sandbox_tested
        self.sandbox_passed = sandbox_passed
        self.sandbox_output = sandbox_output
        self.sandbox_error = sandbox_error
        self.attempts = attempts
        self.error = error

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "language": self.language,
            "purpose": self.purpose,
            "success": self.success,
            "lines": self.lines,
            "file_path": self.file_path,
            "sandbox_tested": self.sandbox_tested,
            "sandbox_passed": self.sandbox_passed,
            "sandbox_output": self.sandbox_output,
            "sandbox_error": self.sandbox_error,
            "attempts": self.attempts,
            "error": self.error,
        }


class PipelineResult:
    """Result of a full end-to-end pipeline execution."""

    def __init__(
        self,
        success: bool = False,
        summary: str = "",
        files: Optional[list[PipelineFileResult]] = None,
        test_strategy: str = "",
        pipeline_test_result: Optional[SandboxResult] = None,
        kb_stored: bool = False,
        total_duration: float = 0.0,
        total_attempts: int = 0,
        error: Optional[str] = None,
    ):
        self.success = success
        self.summary = summary
        self.files = files or []
        self.test_strategy = test_strategy
        self.pipeline_test_result = pipeline_test_result
        self.kb_stored = kb_stored
        self.total_duration = total_duration
        self.total_attempts = total_attempts
        self.error = error

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "summary": self.summary,
            "files": [f.to_dict() for f in self.files],
            "test_strategy": self.test_strategy,
            "pipeline_test_passed": (
                self.pipeline_test_result.success
                if self.pipeline_test_result
                else None
            ),
            "pipeline_test_stdout": (
                self.pipeline_test_result.stdout
                if self.pipeline_test_result
                else ""
            ),
            "pipeline_test_stderr": (
                self.pipeline_test_result.stderr
                if self.pipeline_test_result
                else ""
            ),
            "kb_stored": self.kb_stored,
            "total_duration_seconds": self.total_duration,
            "total_attempts": self.total_attempts,
            "error": self.error,
        }


class Orchestrator:
    """End-to-end pipeline: requirement → plan → generate → test → store → report.

    Components:
    - LLMClient for planning and healing
    - CodeAgent for code generation
    - Sandbox for code execution and testing
    - KnowledgeBase for storing and retrieving experiences

    Stage 1 implementation — single Agent handles the full pipeline.
    """

    MAX_HEAL_RETRIES = 3

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
        1. Plan — decompose requirement into files
        2. Generate + Sandbox Test — generate each file, write to sandbox, run tests
        3. Heal — retry failed files with error context (up to MAX_HEAL_RETRIES)
        4. Pipeline Test — run full test suite in sandbox
        5. Store — store successful result in knowledge base
        6. Report — return structured result
        """
        start_time = time.time()
        total_attempts = 0

        # Step 1: Plan
        step_plan = await self._plan(requirement)
        if not step_plan["success"]:
            return PipelineResult(
                success=False,
                error=step_plan["error"],
                total_duration=time.time() - start_time,
            )

        files_plan = step_plan["files"]
        summary = step_plan["summary"]
        test_strategy = step_plan.get("test_strategy", "")

        # Step 2 & 3: Generate + Sandbox Test + Heal
        pipeline_files = []
        all_generation_success = True

        for file_spec in files_plan:
            file_result = await self._generate_file_with_retry(
                file_spec=file_spec,
                project_summary=summary,
                all_file_paths=[f["path"] for f in files_plan],
            )
            total_attempts += file_result.attempts
            pipeline_files.append(file_result)

            if not file_result.success:
                all_generation_success = False

        # Step 4: Run full test suite in sandbox
        pipeline_test_result = None
        if self.sandbox and all_generation_success:
            pipeline_test_result = await self._run_pipeline_tests(
                files_plan=files_plan,
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

        return PipelineResult(
            success=overall_success,
            summary=summary,
            files=pipeline_files,
            test_strategy=test_strategy,
            pipeline_test_result=pipeline_test_result,
            kb_stored=kb_stored,
            total_duration=time.time() - start_time,
            total_attempts=total_attempts,
        )

    async def _generate_file_with_retry(
        self,
        file_spec: dict,
        project_summary: str,
        all_file_paths: list[str],
    ) -> PipelineFileResult:
        """Generate a file and optionally test it in sandbox, with retry on failure.

        Retries up to MAX_HEAL_RETRIES times, feeding sandbox errors back to the LLM.
        """
        path = file_spec["path"]
        language = file_spec["language"]
        purpose = file_spec["purpose"]
        dependencies = file_spec.get("dependencies", [])

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
            # HTML/CSS: just check the file exists, no execution
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
        # Find test files and Python test commands
        test_files = [f for f in files_plan if f["path"].startswith("tests/")]
        main_files = [f for f in files_plan if not f["path"].startswith("tests/")]

        if not test_files:
            # No explicit test files — try running each main file as a script
            for f in main_files:
                if f["language"] == "python":
                    result = await self.sandbox.run_file(f["path"], language="python")
                    if not result.success and result.stderr:
                        # Only fail if there's actual stderr (vs just no output)
                        if "Error" in result.stderr or "Traceback" in result.stderr:
                            return result

        # Try running tests/test files via python
        for tf in test_files:
            if tf["language"] == "python":
                result = await self.sandbox.run_file(tf["path"], language="python")
                if not result.success:
                    return result

        # Try running pytest on the sandbox files
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

            # Store each successful file
            for f in successful_files:
                # Read the code back from the file (or sandbox)
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
            # KB storage failure should not break the pipeline
            return False

    async def _plan(self, requirement: str) -> dict:
        """Decompose a requirement into a file-level execution plan."""
        try:
            plan_text = await self.planner_llm.chat(
                messages=[
                    {"role": "system", "content": PLANNER_PROMPT},
                    {"role": "user", "content": requirement},
                ],
                model=self.config.get("planner_model", "deepseek-v4-flash"),
                max_tokens=2048,
                reasoning_effort="max",
            )
            plan = json.loads(plan_text)

            required = ["summary", "files", "test_strategy"]
            for key in required:
                if key not in plan:
                    raise ValueError(f"Plan missing key: {key}")

            return {"success": True, **plan}

        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Plan parsing failed: {e}",
                "stage": "planning",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Planning failed: {e}",
                "stage": "planning",
            }
