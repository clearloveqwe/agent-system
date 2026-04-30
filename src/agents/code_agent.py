"""CodeAgent — generates, modifies, and tests code for a specific domain."""

import os
from typing import Optional

from .base import BaseAgent
from src.common.llm_client import LLMClient

# System prompt for code generation
SYSTEM_PROMPT = """You are an expert software engineer. Generate production-ready code following these rules:

1. Write clean, well-documented code with type hints
2. Follow the language/framework best practices
3. Include error handling for edge cases
4. Output ONLY the code file content — no explanations, no markdown wrappers
5. Use the exact file path and structure specified in the task

If the task is unclear, state your assumptions before generating code."""


class CodeAgent(BaseAgent):
    """Agent specialized in code generation and modification.

    Takes a task description and generates production-ready code files.
    """

    def __init__(self, role: str = "developer", model_config: Optional[dict] = None):
        super().__init__(role, model_config)
        self.llm = LLMClient(model_config or {})
        self.model = (model_config or {}).get("model", "deepseek-chat")
        self.reasoning_effort = (model_config or {}).get("reasoning_effort")

    async def execute(self, task: dict) -> dict:
        """Execute a code generation task.

        Task format:
        {
            "requirement": "Generate a React Todo component...",
            "language": "python" | "javascript" | "typescript",
            "target_path": "src/components/Todo.tsx",  # optional
            "context": { ... },  # optional extra context
        }
        """
        requirement = task.get("requirement", "")
        language = task.get("language", "python")
        target_path = task.get("target_path")
        context = task.get("context", {})

        if not requirement:
            return {"success": False, "error": "No requirement provided"}

        # Build prompt
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": self._build_prompt(requirement, language, target_path, context),
            },
        ]

        # Generate code
        try:
            code = await self.llm.chat(
                messages=messages,
                model=self.model,
                temperature=0.2,
                max_tokens=4096,
                reasoning_effort=self.reasoning_effort,
            )
        except Exception as e:
            return {
                "success": False,
                "error": f"LLM call failed: {e}",
                "stage": "generation",
            }

        # Clean up code output
        code = self._clean_code(code)

        # Write to file if target_path specified
        if target_path:
            try:
                abs_path = os.path.abspath(target_path)
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                with open(abs_path, "w") as f:
                    f.write(code)
                return {
                    "success": True,
                    "code": code,
                    "file_path": abs_path,
                    "language": language,
                    "lines": len(code.splitlines()),
                }
            except Exception as e:
                return {
                    "success": True,
                    "code": code,
                    "language": language,
                    "error": f"Generated but failed to write file: {e}",
                }

        return {
            "success": True,
            "code": code,
            "language": language,
            "lines": len(code.splitlines()),
        }

    def _build_prompt(
        self,
        requirement: str,
        language: str,
        target_path: Optional[str],
        context: dict,
    ) -> str:
        """Build the code generation prompt."""
        parts = [f"Generate {language} code for the following requirement:\n\n{requirement}"]
        if target_path:
            parts.append(f"\n\nFile path: {target_path}")
        if context:
            parts.append(f"\n\nContext:\n{context}")

        parts.append(
            "\n\nRules:\n"
            "- Output ONLY the code, no explanations\n"
            "- Include all necessary imports\n"
            "- Add type hints where applicable\n"
            "- Handle errors gracefully"
        )
        return "\n".join(parts)

    def _clean_code(self, code: str) -> str:
        """Remove markdown code fences if the model wraps output."""
        code = code.strip()
        if code.startswith("```"):
            # Remove opening fence (possibly with language tag)
            first_newline = code.find("\n")
            if first_newline != -1:
                code = code[first_newline + 1:]
            # Remove closing fence
            if code.endswith("```"):
                code = code[:-3]
            elif code.endswith("```\n"):
                code = code[:-4]
        return code.strip()
