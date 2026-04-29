"""Orchestrator — single Agent loop: requirement → plan → code → output."""

import json
import os
from typing import Optional

from src.agents.code_agent import CodeAgent
from src.common.llm_client import LLMClient

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
  "test_strategy": "How to verify this works"
}

Rules:
- Break the requirement into the minimum set of files needed
- Each file should have a single responsibility
- Include test files
- Use relative paths from the project root
"""


class Orchestrator:
    """Single-Agent orchestration loop: requirement → plan → code → output.

    Stage 1 implementation — one agent handles the entire pipeline.
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.planner_llm = LLMClient(self.config.get("planner", {}))
        self.code_agent = CodeAgent(
            model_config=self.config.get("code_agent", {})
        )

    async def run(self, requirement: str) -> dict:
        """Execute a full development cycle from a natural language requirement.

        Steps:
        1. Plan — decompose requirement into files
        2. Generate — use CodeAgent for each file
        3. Report — return all generated code with metadata
        """
        step_plan = await self._plan(requirement)
        if not step_plan.get("success"):
            return step_plan

        files_plan = step_plan["files"]
        generated = []

        for file_spec in files_plan:
            result = await self.code_agent.execute({
                "requirement": file_spec["purpose"],
                "language": file_spec["language"],
                "target_path": file_spec["path"],
                "context": {
                    "project_summary": step_plan["summary"],
                    "all_files": [f["path"] for f in files_plan],
                },
            })

            generated.append({
                "path": file_spec["path"],
                "language": file_spec["language"],
                "purpose": file_spec["purpose"],
                "success": result.get("success", False),
                "lines": result.get("lines", 0),
                "file_path": result.get("file_path"),
                "error": result.get("error"),
            })

        all_success = all(g["success"] for g in generated)

        return {
            "success": all_success,
            "summary": step_plan["summary"],
            "test_strategy": step_plan["test_strategy"],
            "files": generated,
            "total_files": len(generated),
            "total_lines": sum(g["lines"] for g in generated if g.get("lines")),
        }

    async def _plan(self, requirement: str) -> dict:
        """Decompose a requirement into a file-level execution plan."""
        try:
            plan_text = await self.planner_llm.chat(
                messages=[
                    {"role": "system", "content": PLANNER_PROMPT},
                    {"role": "user", "content": requirement},
                ],
                model=self.config.get("planner_model", "deepseek-chat"),
                temperature=0.1,
                max_tokens=2048,
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
