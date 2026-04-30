"""Pydantic schemas for the Agent pipeline — structured data models with JSON Schema support.

All pipeline data flows through these models, providing:
- Type validation at every boundary
- JSON Schema generation for LLM response_format
- Auto-correction on validation failure
- Drop-in replacement for old hand-written data classes
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ── Planning Schemas ────────────────────────────────────────────


class FileSpec(BaseModel):
    """Specification for a single file in a project plan."""

    path: str = Field(description="Relative file path from project root")
    language: str = Field(description="Programming language (python|javascript|typescript|html|css|sql)")
    purpose: str = Field(description="What this file does")
    dependencies: list[str] = Field(
        default_factory=list,
        description="Other file paths this file depends on",
    )


class ProjectPlan(BaseModel):
    """Parsed plan from the LLM planner — file breakdown of a user requirement.

    This model drives the entire pipeline: Orchestrator._plan() returns a
    validated ProjectPlan, which then drives code generation and testing.
    """

    summary: str = Field(description="Brief description of what needs to be built")
    files: list[FileSpec] = Field(description="Files to generate, in dependency order")
    test_strategy: str = Field(
        description="How to verify this works: test file paths and commands"
    )


class PlanDraft(BaseModel):
    """A plan draft for user discussion and refinement cycle.

    Usage:
        draft = await orchestrator.plan_draft(requirement)
        # Show draft.present() to user, collect feedback
        draft = await orchestrator.plan_refine(draft, feedback)
        # Repeat until user confirms, then:
        result = await orchestrator.run_with_plan(draft.plan)
    """

    plan: ProjectPlan = Field(description="The current proposed plan")
    alternatives: list[ProjectPlan] = Field(
        default_factory=list,
        description="Alternative approaches offered alongside the main plan",
    )
    discussion: list[dict] = Field(
        default_factory=list,
        description="Discussion history: [{'role': 'user'|'assistant', 'content': ...}]",
    )
    confirmed: bool = False
    iteration: int = 1

    def present(self) -> str:
        """Format the draft for display to the user."""
        lines = [f"## 📋 Architecture Draft (v{self.iteration})"]
        lines.append("")
        lines.append(f"**Summary:** {self.plan.summary}")
        lines.append("")
        lines.append("### Files")
        for f in self.plan.files:
            dep_str = f" (depends on: {', '.join(f.dependencies)})" if f.dependencies else ""
            lines.append(f"- `{f.path}` — {f.purpose}{dep_str}")
        lines.append("")
        lines.append(f"**Test Strategy:** {self.plan.test_strategy}")

        if self.alternatives:
            lines.append("")
            lines.append("### Alternative Architectures")
            for i, alt in enumerate(self.alternatives, 1):
                lines.append("")
                lines.append(f"**Option {i}:** {alt.summary}")
                for f in alt.files:
                    lines.append(f"  - `{f.path}` — {f.purpose}")

        if self.discussion:
            lines.append("")
            lines.append("### Discussion History")
            for entry in self.discussion[-3:]:  # Last 3 messages
                role = "👤 You" if entry["role"] == "user" else "🤖 Architect"
                content = entry["content"][:200]
                lines.append(f"- **{role}:** {content}")

        lines.append("")
        lines.append("---")
        lines.append("*Reply with feedback to refine, or send `confirm` to proceed.*")
        return "\n".join(lines)


# ── Sandbox Result Schema ───────────────────────────────────────


class SandboxResultSchema(BaseModel):
    """Structured result from sandbox code execution (mirrors SandboxResult in base.py)."""

    success: bool = False
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    error: Optional[str] = None


# ── Pipeline Result Schemas ─────────────────────────────────────


class PipelineFileResult(BaseModel):
    """Result for a single file in the pipeline.

    Replaces the old hand-written PipelineFileResult class.
    Use .model_dump() instead of .to_dict() for serialization.
    """

    path: str = ""
    language: str = ""
    purpose: str = ""
    success: bool = False
    lines: int = 0
    file_path: Optional[str] = None
    sandbox_tested: bool = False
    sandbox_passed: Optional[bool] = None
    sandbox_output: str = ""
    sandbox_error: str = ""
    attempts: int = 1
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Alias for .model_dump() — backward compatibility."""
        return self.model_dump()


class PipelineTestResult(BaseModel):
    """Structured result of the full pipeline test run."""

    success: bool = False
    stdout: str = ""
    stderr: str = ""


class PipelineResult(BaseModel):
    """Result of a full end-to-end pipeline execution.

    Replaces the old hand-written PipelineResult class.
    Use .model_dump() instead of .to_dict() for serialization.
    """

    success: bool = False
    summary: str = ""
    files: list[PipelineFileResult] = Field(default_factory=list)
    test_strategy: str = ""
    pipeline_test: Optional[PipelineTestResult] = None
    kb_stored: bool = False
    total_duration: float = 0.0
    total_attempts: int = 0
    error: Optional[str] = None
    corrections: int = 0  # How many times the LLM corrected its output

    def to_dict(self) -> dict:
        """Alias for .model_dump() — backward compatibility."""
        return self.model_dump()


# ── Knowledge Entry Schema ──────────────────────────────────────


class KnowledgeEntrySchema(BaseModel):
    """Schema for knowledge base entries (serialization/deserialization)."""

    requirement: str
    solution: str
    language: str = ""
    entry_type: str = "code_gen"
    metadata: dict = Field(default_factory=dict)
    entry_id: Optional[str] = None
    created_at: Optional[str] = None
