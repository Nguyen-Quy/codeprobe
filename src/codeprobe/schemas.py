from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskCategory(str, Enum):
    INVESTIGATION = "investigation"
    DEBUGGING = "debugging"
    REFACTORING = "refactoring"
    CODE_EDIT = "code_edit"
    TESTING = "testing"
    MODEL_ROUTING = "model_routing"
    GENERAL = "general"


class QueryDomain(str, Enum):
    INFRA_DEVOPS = "infra_devops"
    APPLICATION_LOGIC = "application_logic"
    HYBRID = "hybrid"


class InvestigationMode(str, Enum):
    AUTO = "auto"
    CODE_MODIFICATION = "code"
    AUDIT_COMPARE = "compare"
    SURVEY_EXPLORATION = "survey"


class ActionType(str, Enum):
    SEARCH_SYMBOL = "search_symbol"
    GREP_TEXT = "grep_text"
    READ_FILE_SLICE = "read_file_slice"
    READ_FULL_FILE = "read_full_file"
    GIT_STATUS = "git_status"
    GIT_DIFF = "git_diff"
    GIT_LOG = "git_log"
    RUN_TESTS = "run_tests"
    PROCEED_WITH_EDIT = "proceed_with_edit"
    SYNTHESIZE_ANSWER = "synthesize_answer"
    STOP_AND_ANSWER = "stop_and_answer"
    DELEGATE_SUBAGENT = "delegate_subagent"


class ModelTier(str, Enum):
    FAST_INFER = "fast_infer"  # e.g., Flash, Haiku, small local LLM
    STANDARD = "standard"  # e.g., Sonnet, GPT-4o, Devstral-24B
    REASONING_HEAVY = "reasoning"  # e.g., Opus, o3, Gemini-Pro reasoning


class RecommendedAction(BaseModel):
    action: ActionType = Field(
        ..., description="The recommended action type to perform next"
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Action arguments (e.g. query, path, line_range)",
    )
    priority: int = Field(default=1, description="Execution priority (1 = highest)")
    rationale: str = Field(default="", description="Why this action is recommended")


class DecisionRequest(BaseModel):
    user_goal: str = Field(..., description="The high-level goal or user prompt")
    task_category: TaskCategory | None = Field(
        default=None,
        description="Optional category hint (e.g. investigation, debugging, refactoring)",
    )
    current_step: int = Field(default=0, description="Current iteration or turn number")
    collected_evidence: list[str] = Field(
        default_factory=list, description="Raw or condensed evidence collected so far"
    )
    known_files: list[str] = Field(
        default_factory=list, description="Relevant file paths discovered so far"
    )
    modified_files: list[str] = Field(
        default_factory=list, description="Files currently modified in working tree"
    )
    last_error: str | None = Field(
        default=None, description="Last error message, trace, or test failure"
    )
    active_file: str | None = Field(
        default=None, description="Currently active or open file"
    )
    budget_remaining_steps: int = Field(
        default=5, description="Maximum steps remaining before forcing conclusion"
    )


class DecisionResponse(BaseModel):
    strategy: str = Field(
        ...,
        description="High level strategy summary (e.g. BROAD_SEARCH, DEEP_INSPECT, VERIFY_TESTS, READY_TO_ANSWER)",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score of the routing decision (0.0 - 1.0)",
    )
    recommended_actions: list[RecommendedAction] = Field(
        default_factory=list, description="Ordered list of recommended next actions"
    )
    prohibited_actions: list[str] = Field(
        default_factory=list,
        description="Actions forbidden at this stage (e.g. 'do_not_edit_without_running_tests')",
    )
    suggested_model_tier: ModelTier = Field(
        default=ModelTier.STANDARD,
        description="Recommended model tier for executing the next step",
    )
    is_sufficient: bool = Field(
        default=False,
        description="Whether enough evidence/context has been gathered to resolve the user goal",
    )
    raw_probabilities: dict[str, float] = Field(
        default_factory=dict,
        description="Raw noul probability scores from Laya question matrix",
    )
    reasoning: str = Field(
        default="", description="Detailed explanation justifying the decision"
    )


class InvestigationRequest(BaseModel):
    query: str = Field(
        ..., description="User query, bug description, or feature/phase progress goal"
    )
    target_files: list[str] | None = Field(
        default=None, description="Optional list of specific files to prioritize"
    )
    max_steps: int = Field(
        default=5, ge=1, le=15, description="Maximum recursive exploration steps"
    )
    synthesize_summary: bool = Field(
        default=True, description="Whether to synthesize a comprehensive answer text"
    )


class CodeTarget(BaseModel):
    file_path: str = Field(
        ..., description="Target file path relative to workspace root"
    )
    role: str = Field(
        default="primary_source",
        description="Role of this target (e.g. primary_source, config_binding, infra_manifest)",
    )
    start_line: int = Field(
        ..., description="1-indexed starting line number of the code block"
    )
    end_line: int = Field(
        ..., description="1-indexed ending line number of the code block"
    )
    current_code: str = Field(
        ..., description="Verbatim code snippet currently in file"
    )
    target_content: str = Field(
        ...,
        description="Exact string sequence to match and replace (for replace_file_content)",
    )
    replacement_content: str = Field(
        ...,
        description="Proposed replacement code with proper indentation and structure",
    )
    diff_preview: str = Field(
        default="",
        description="Unified diff preview formatted as markdown diff block",
    )


class ReadyToCodePayload(BaseModel):
    summary: str = Field(
        ...,
        description="Summary of the code modification objective",
    )
    targets: list[CodeTarget] = Field(
        default_factory=list,
        description="Ordered list of code/config targets ready for immediate editing",
    )
    blast_radius: list[str] = Field(
        default_factory=list,
        description="Callers, dependent services, or manifests potentially impacted",
    )
    confidence: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Confidence score for this ready-to-code payload",
    )


class ComparisonTarget(BaseModel):
    aspect: str = Field(
        ..., description="Feature, component, or task area being compared"
    )
    source_component: str = Field(
        ...,
        description="Reference implementation or source component (e.g. bash script)",
    )
    target_component: str = Field(
        ..., description="Target implementation or target component (e.g. rust crate)"
    )
    parity_status: str = Field(
        ...,
        description="Parity status: 'EQUIVALENT', 'PARTIAL', 'MISSING_IN_TARGET', 'EXTENDED'",
    )
    missing_in_target: list[str] = Field(
        default_factory=list,
        description="Concrete list of missing capabilities in target",
    )
    details: str = Field(
        default="", description="Detailed comparison notes or evaluation"
    )


class ComparisonMatrixPayload(BaseModel):
    title: str = Field(..., description="Title of comparison matrix")
    subsystems_detected: list[str] = Field(
        default_factory=list, description="Subsystems or languages being compared"
    )
    component_pairs: list[ComparisonTarget] = Field(
        default_factory=list, description="List of component comparison pairs"
    )
    architectural_gaps: list[str] = Field(
        default_factory=list,
        description="High-level architectural gaps or missing capabilities",
    )


class InvestigationResult(BaseModel):
    investigation_id: str = Field(
        default="",
        description="Unique investigation identifier for feedback and trajectory tracking",
    )
    user_goal: str = Field(..., description="Original user goal")
    strategy: str = Field(..., description="Final execution strategy")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    summary: str = Field(
        ...,
        description="Synthesized conclusion and direct answer with facts and code citations",
    )
    actionable_guidance: str = Field(
        default="CRITICAL DIRECTIVE FOR AGENT: Use the above synthesized findings directly to complete the user request. Do NOT discard this evidence or re-explore the codebase from scratch.",
        description="Mandatory instruction for the consuming AI agent",
    )
    suggested_next_actions: list[str] = Field(
        default_factory=list,
        description="Specific next steps recommended for the agent",
    )
    examined_files: list[str] = Field(
        default_factory=list, description="Files inspected during investigation"
    )
    discovered_symbols: list[str] = Field(
        default_factory=list,
        description="Key symbols, functions, or entities discovered",
    )
    is_sufficient: bool = Field(
        default=True, description="Whether enough evidence was found"
    )
    is_incomplete: bool = Field(
        default=False,
        description="Whether discovery was bounded/interrupted by navigation budget",
    )
    steps_executed: int = Field(
        default=1, description="Number of iterative probe steps executed"
    )
    evidence_snippets: list[str] = Field(
        default_factory=list, description="Top relevant evidence snippets collected"
    )
    retracted_files: list[str] = Field(
        default_factory=list, description="Candidate files retracted as false positives"
    )
    cross_file_links: list[str] = Field(
        default_factory=list, description="Cross-file call or reference relationships"
    )
    sufficiency_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Overall context sufficiency score (0.0 to 1.0)",
    )
    hop_count: int = Field(
        default=1,
        description="Number of autonomous multi-hop traversal rounds executed",
    )
    missing_aspects: list[str] = Field(
        default_factory=list,
        description="List of missing context aspects if sufficiency < 0.8",
    )
    verified_facts: list[str] = Field(
        default_factory=list,
        description="Deduplicated, confirmed codebase facts with source and line provenance",
    )
    unresolved_gaps: list[str] = Field(
        default_factory=list,
        description="Missing aspects or unresolved questions identified by evidence manager",
    )
    exemplar_file: str | None = Field(
        default=None,
        description="Structurally similar reference/exemplar file for new code",
    )
    mounting_point: str | None = Field(
        default=None,
        description="Registration/router/entrypoint file for mounting new code",
    )
    ready_to_code: ReadyToCodePayload | None = Field(
        default=None,
        description="Structured ready-to-code payload with exact file targets, anchors, and diff previews",
    )
    mode: InvestigationMode = Field(
        default=InvestigationMode.AUTO,
        description="Active investigation mode (code, compare, survey, auto)",
    )
    comparison_matrix: ComparisonMatrixPayload | None = Field(
        default=None,
        description="Structured feature parity and gap comparison matrix if mode is compare",
    )
    needs_clarification: bool = Field(
        default=False,
        description="Whether query was too ambiguous and requires clarification before running deep recon",
    )
    clarification_questions: list[str] = Field(
        default_factory=list,
        description="Questions for user or agent to clarify intent when needs_clarification is True",
    )


class InvestigationFeedback(BaseModel):
    investigation_id: str = Field(
        ..., description="ID of the investigation being evaluated"
    )
    score: int = Field(
        ..., ge=1, le=5, description="Quality score from 1 (poor) to 5 (excellent)"
    )
    feedback_text: str | None = Field(
        default=None, description="Optional textual feedback, critique, or correction"
    )
    helpful_files: list[str] | None = Field(
        default=None, description="Files that were particularly helpful"
    )
    unhelpful_files: list[str] | None = Field(
        default=None, description="Files that were noise or irrelevant"
    )
    workspace_path: str | None = Field(
        default=None, description="Workspace path to store feedback and train weights"
    )


class FeedbackResponse(BaseModel):
    status: str = Field(
        default="recorded", description="Status of the feedback processing"
    )
    investigation_id: str = Field(..., description="ID of the evaluated investigation")
    learned_updates_count: int = Field(
        default=0, description="Number of weight adjustments made"
    )
    message: str = Field(default="", description="Summary of calibration adjustments")


@dataclass
class DeclarationUnit:
    name: str
    kind: str  # "class", "function", "method", "interface", "struct", "trait", "snippet", "infra"
    file_path: str
    start_line: int
    end_line: int
    signature: str
    docstring: str | None = None
    body_snippet: str = ""
    calls: list[str] = field(default_factory=list)

    def format_verbatim(self) -> str:
        doc = f'\n  """{self.docstring}"""' if self.docstring else ""
        return (
            f"[{self.kind.upper()}] {self.name} (Lines {self.start_line}-{self.end_line}):\n"
            f"  {self.signature}{doc}\n"
            f"  Calls: {', '.join(self.calls) if self.calls else 'None'}\n"
            f"  Excerpt:\n{self.body_snippet}"
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "signature": self.signature,
            "docstring": self.docstring,
            "body_snippet": self.body_snippet,
            "calls": self.calls,
        }
