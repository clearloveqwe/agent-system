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


# ── Clarification (Handoff) Schemas ──────────────────────────────


class FunctionalRequirement(BaseModel):
    """A single functional requirement in the clarified spec."""

    id: str = Field(description="Unique identifier")
    description: str = Field(description="Clear functional description, avoid implementation details")
    user_story: str = Field(default="", description="Optional user story to convey intent")
    acceptance_criteria: list[str] = Field(default_factory=list, description="Acceptance criteria list")
    priority: str = Field(default="must", description="Priority level (must/should/could)")


class NonFunctionalRequirement(BaseModel):
    """Non-functional requirement for the project."""

    category: str = Field(description="Category: performance, security, usability, etc.")
    description: str = Field(description="What is required")
    target_value: Optional[str] = Field(default=None, description="Measurable target, e.g. 'page load < 2s'")


class ClarifiedRequirement(BaseModel):
    """The handoff document between discuss_llm and planner_llm.

    Produced by discuss_llm after a multi-turn clarification conversation.
    Consumed by planner_llm to generate a ProjectPlan.
    """

    project_name: str
    project_goal: str = Field(description="Project goal in 1-2 sentences")
    target_users: Optional[str] = Field(default=None, description="Target user description")
    functional_requirements: list[FunctionalRequirement] = Field(
        description="Functional requirements the project must satisfy"
    )
    non_functional_requirements: list[NonFunctionalRequirement] = Field(
        default_factory=list,
        description="Non-functional requirements (performance, security, etc.)",
    )
    tech_stack_preference: Optional[dict] = Field(
        default=None,
        description="Preferred tech stack, e.g. {'frontend': 'React', 'backend': 'FastAPI'}",
    )
    constraints: Optional[str] = Field(default=None, description="Time, budget, compliance constraints")
    confirmed_assumptions: list[str] = Field(
        default_factory=list,
        description="Assumptions the user has confirmed during the conversation",
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="Questions that could not be resolved; flagged as risk for planner",
    )


class ClarifyResponse(BaseModel):
    """discuss_llm response during a clarification conversation.

    - action='ask': LLM wants to ask the user another question
    - action='submit': LLM has enough info and is submitting the final spec
    """

    action: str = Field(pattern="^(ask|submit)$")
    question: str = Field(default="", description="Question for the user (when action=ask)")
    summary_so_far: str = Field(default="", description="Brief summary of what's been gathered so far")

    # Populated only when action='submit'
    clarification: Optional[ClarifiedRequirement] = Field(
        default=None,
        description="Final clarified requirement (only when action=submit)",
    )


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
