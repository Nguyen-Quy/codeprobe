from __future__ import annotations

import logging
import os

from laya import Router

from ..config import ProjectConfig, load_config
from ..schemas import (
    ActionType,
    DecisionRequest,
    DecisionResponse,
    ModelTier,
    RecommendedAction,
    TaskCategory,
)
from .matrices import MATRICES, DecisionMatrix
from .synthesizer import StateSynthesizer

logger = logging.getLogger(__name__)


class LayaDecisionRouter:
    """
    Universal Decision Router engine for codeprobe.
    Evaluates agent requests using deterministic multi-domain heuristic matrices
    with configurable project guardrails and optional Laya probabilistic model inference.
    """

    def __init__(
        self,
        default_threshold: float | None = None,
        enable_laya: bool = False,
        config: ProjectConfig | None = None,
    ) -> None:
        self.config = config or load_config()
        self.default_threshold = (
            default_threshold
            if default_threshold is not None
            else self.config.thresholds.default
        )
        self.enable_laya = (
            enable_laya or os.environ.get("CODEPROBE_ENABLE_LAYA", "0") == "1"
        )
        self._router_instance = None
        if self.enable_laya:
            self._init_laya_router()

    def _init_laya_router(self) -> None:
        try:
            self._router_instance = Router()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Could not initialize laya.Router (%s). Falling back to heuristic engine.",
                exc,
            )
            self._router_instance = None

    def route(self, request: DecisionRequest) -> DecisionResponse:
        """
        Main entrypoint: takes a DecisionRequest and produces a structured DecisionResponse.
        """
        category = request.task_category or self._infer_category(request)
        matrix = MATRICES.get(category, MATRICES[TaskCategory.INVESTIGATION])
        synthesized_state = StateSynthesizer.synthesize_prompt(request)

        # 1. Predict probabilities via Laya Router (or fallback heuristics)
        raw_probs = self._predict_probabilities(synthesized_state, matrix, request)

        # 2. Map probabilities & rules to DecisionResponse
        return self._build_decision_response(request, category, raw_probs)

    def _infer_category(self, request: DecisionRequest) -> TaskCategory:
        goal_lower = request.user_goal.lower()

        # Model Routing
        if any(
            k in goal_lower
            for k in [
                "model tier",
                "model routing",
                "route model",
                "select model",
                "llm tier",
            ]
        ):
            return TaskCategory.MODEL_ROUTING

        # Testing & Verification
        if any(
            k in goal_lower
            for k in [
                "pytest",
                "run tests",
                "verify tests",
                "test suite",
                "check test",
                "coverage",
                "assert",
            ]
        ):
            return TaskCategory.TESTING

        # Debugging & Error Handling
        if request.last_error or any(
            k in goal_lower
            for k in [
                "fix",
                "error",
                "bug",
                "fail",
                "exception",
                "traceback",
                "crash",
                "zerodivisionerror",
                "assertionerror",
                "indexerror",
                "keyerror",
                "timeout",
            ]
        ):
            return TaskCategory.DEBUGGING

        # Refactoring & Code Modification
        if any(
            k in goal_lower
            for k in [
                "refactor",
                "cleanup",
                "restructure",
                "optimize",
                "rename",
                "extract function",
                "extract method",
            ]
        ):
            return TaskCategory.REFACTORING

        if any(
            k in goal_lower
            for k in [
                "edit",
                "modify",
                "update code",
                "change implementation",
                "add feature",
            ]
        ):
            return TaskCategory.CODE_EDIT

        return TaskCategory.INVESTIGATION

    def _predict_probabilities(
        self,
        state: str,
        matrix: DecisionMatrix,
        request: DecisionRequest,
    ) -> dict[str, float]:
        if self._router_instance is not None:
            try:
                res = self._router_instance.predict(state, matrix.questions)
                answers = res.get("answers", {})
                probs: dict[str, float] = {}
                for key in matrix.questions:
                    if key in answers and "noul" in answers[key]:
                        probs[key] = float(answers[key]["noul"])
                    else:
                        probs[key] = 0.0
                return probs
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Laya router prediction failed: %s. Using heuristic fallback.", exc
                )

        return self._heuristic_fallback_probabilities(matrix, request)

    def _heuristic_fallback_probabilities(
        self,
        matrix: DecisionMatrix,
        request: DecisionRequest,
    ) -> dict[str, float]:
        probs: dict[str, float] = {}
        evidence_text = "\n".join(request.collected_evidence)
        evidence_count = len(request.collected_evidence)
        has_error = bool(request.last_error)
        has_files = bool(request.known_files)
        tests_green = (
            "passed" in evidence_text.lower() or "passed in" in evidence_text.lower()
        )
        tests_failing = (
            "failed" in evidence_text.lower() or "error" in evidence_text.lower()
        )

        if matrix.category in (TaskCategory.INVESTIGATION, TaskCategory.GENERAL):
            if evidence_count == 0:
                probs["need_search"] = 0.95
                probs["need_file_read"] = 0.20
                probs["need_git"] = 0.40
                probs["need_schema"] = 0.30
                probs["need_tests"] = 0.10
                probs["enough_evidence"] = 0.05
            elif not has_files:
                probs["need_search"] = 0.85
                probs["need_file_read"] = 0.10
                probs["need_git"] = 0.50
                probs["need_schema"] = 0.30
                probs["need_tests"] = 0.10
                probs["enough_evidence"] = 0.20
            elif evidence_count >= 3:
                probs["need_search"] = 0.30
                probs["need_file_read"] = 0.40
                probs["need_git"] = 0.20
                probs["need_schema"] = 0.10
                probs["need_tests"] = 0.20
                probs["enough_evidence"] = 0.80
            else:
                probs["need_search"] = 0.40
                probs["need_file_read"] = 0.85
                probs["need_git"] = 0.30
                probs["need_schema"] = 0.20
                probs["need_tests"] = 0.20
                probs["enough_evidence"] = 0.40

        elif matrix.category == TaskCategory.DEBUGGING:
            if not evidence_count:
                probs["need_reproduce"] = 0.85
                probs["need_trace_error"] = 0.90 if has_error else 0.50
                probs["need_git_blame"] = 0.40
                probs["ready_to_fix"] = 0.15
                probs["enough_evidence"] = 0.10
            elif evidence_count >= 2 and has_files:
                probs["need_reproduce"] = 0.30
                probs["need_trace_error"] = 0.40
                probs["need_git_blame"] = 0.20
                probs["ready_to_fix"] = 0.85
                probs["enough_evidence"] = 0.80
            else:
                probs["need_reproduce"] = 0.50
                probs["need_trace_error"] = 0.80 if has_error else 0.40
                probs["need_git_blame"] = 0.30
                probs["ready_to_fix"] = 0.40
                probs["enough_evidence"] = 0.40

        elif matrix.category in (TaskCategory.REFACTORING, TaskCategory.CODE_EDIT):
            if evidence_count < 2:
                probs["need_usage_search"] = 0.90
                probs["need_test_coverage"] = 0.85
                probs["ready_to_edit"] = 0.20
                probs["enough_evidence"] = 0.20
            else:
                probs["need_usage_search"] = 0.30
                probs["need_test_coverage"] = 0.40
                probs["ready_to_edit"] = 0.85
                probs["enough_evidence"] = 0.80

        elif matrix.category == TaskCategory.TESTING:
            if tests_green:
                probs["need_run_existing"] = 0.20
                probs["need_new_test"] = 0.30
                probs["need_regression_check"] = 0.20
                probs["tests_passing"] = 0.95
                probs["enough_evidence"] = 0.90
            elif tests_failing or has_error:
                probs["need_run_existing"] = 0.85
                probs["need_new_test"] = 0.40
                probs["need_regression_check"] = 0.70
                probs["tests_passing"] = 0.10
                probs["enough_evidence"] = 0.20
            elif evidence_count == 0:
                probs["need_run_existing"] = 0.90
                probs["need_new_test"] = 0.50
                probs["need_regression_check"] = 0.40
                probs["tests_passing"] = 0.10
                probs["enough_evidence"] = 0.10
            else:
                probs["need_run_existing"] = 0.40
                probs["need_new_test"] = 0.80
                probs["need_regression_check"] = 0.40
                probs["tests_passing"] = 0.50
                probs["enough_evidence"] = 0.60

        elif matrix.category == TaskCategory.MODEL_ROUTING:
            goal_lower = request.user_goal.lower()
            if any(
                k in goal_lower
                for k in [
                    "grep",
                    "find symbol",
                    "lookup",
                    "simple",
                    "minor",
                    "single file",
                    "read file",
                ]
            ):
                probs["is_trivial_task"] = 0.95
                probs["standard_coding"] = 0.20
                probs["requires_deep_reasoning"] = 0.05
            elif any(
                k in goal_lower
                for k in [
                    "architecture",
                    "concurrency",
                    "race condition",
                    "distributed",
                    "subtle",
                    "complex refactor",
                    "deadlock",
                ]
            ):
                probs["is_trivial_task"] = 0.05
                probs["standard_coding"] = 0.30
                probs["requires_deep_reasoning"] = 0.95
            else:
                probs["is_trivial_task"] = 0.20
                probs["standard_coding"] = 0.85
                probs["requires_deep_reasoning"] = 0.40

        for k in matrix.questions:
            probs.setdefault(k, 0.0)

        return probs

    def _build_decision_response(
        self,
        request: DecisionRequest,
        category: TaskCategory,
        probs: dict[str, float],
    ) -> DecisionResponse:
        actions: list[RecommendedAction] = []
        prohibited: list[str] = []
        reasons: list[str] = []

        threshold = self.config.get_threshold(category)
        max_slice_lines = self.config.policy.max_file_slice_lines

        # Check for forbidden files in known / modified files
        for f in request.known_files + request.modified_files:
            if self.config.is_file_forbidden(f):
                prohibited.append(f"forbidden_file_access:{f}")

        is_sufficient = (
            probs.get("enough_evidence", 0.0) >= threshold
            or probs.get("tests_passing", 0.0) >= threshold
            or request.budget_remaining_steps <= 1
        )

        # Model tier determination & config override
        tier_override = self.config.get_model_tier_override(category)
        if tier_override is not None:
            tier = tier_override
        elif category == TaskCategory.MODEL_ROUTING:
            if probs.get("is_trivial_task", 0.0) >= threshold:
                tier = ModelTier.FAST_INFER
            elif probs.get("requires_deep_reasoning", 0.0) >= threshold:
                tier = ModelTier.REASONING_HEAVY
            else:
                tier = ModelTier.STANDARD
        elif is_sufficient:
            tier = ModelTier.STANDARD
        elif probs.get("need_search", 0.0) > 0.80 and not request.collected_evidence:
            tier = ModelTier.FAST_INFER
        elif category in (TaskCategory.DEBUGGING, TaskCategory.REFACTORING):
            tier = ModelTier.REASONING_HEAVY
        else:
            tier = ModelTier.STANDARD

        strategy = "GENERAL_INVESTIGATION"

        if is_sufficient:
            strategy = "READY_TO_SYNTHESIZE"
            reasons.append(
                "Evidence threshold met. Sufficient context to address the user goal."
            )
            actions.append(
                RecommendedAction(
                    action=ActionType.SYNTHESIZE_ANSWER,
                    params={
                        "evidence_summary": f"Synthesizing conclusions from {len(request.collected_evidence)} evidence records."
                    },
                    priority=1,
                    rationale="Formulate final solution with gathered repository evidence.",
                )
            )
        else:
            # 1. Error Tracing
            if probs.get("need_trace_error", 0.0) >= threshold:
                strategy = "TRACE_ERROR"
                reasons.append(
                    f"Error trace inspection indicated ({probs['need_trace_error']:.2f})."
                )
                candidate_files = [
                    f
                    for f in (
                        request.known_files
                        or StateSynthesizer.extract_file_paths(request.last_error or "")
                    )
                    if not self.config.is_file_forbidden(f)
                ]
                actions.append(
                    RecommendedAction(
                        action=ActionType.READ_FILE_SLICE,
                        params={
                            "candidate_files": candidate_files[:4],
                            "focus_lines": f"1-{max_slice_lines}",
                            "error_context": (request.last_error or "")[:300],
                        },
                        priority=1,
                        rationale="Inspect stack trace location to pinpoint error cause.",
                    )
                )

            # 2. Reproduction & Testing
            if (
                probs.get("need_reproduce", 0.0) >= threshold
                or probs.get("need_run_existing", 0.0) >= threshold
                or probs.get("need_regression_check", 0.0) >= threshold
            ):
                if strategy == "GENERAL_INVESTIGATION":
                    strategy = (
                        "REPRODUCE_ERROR"
                        if probs.get("need_reproduce", 0.0) >= threshold
                        else "VERIFY_TESTS"
                    )
                test_targets = [
                    f
                    for f in request.known_files
                    if "test" in f and not self.config.is_file_forbidden(f)
                ] or request.known_files[:2]
                actions.append(
                    RecommendedAction(
                        action=ActionType.RUN_TESTS,
                        params={
                            "test_command": "pytest -v",
                            "target_files": test_targets,
                        },
                        priority=2,
                        rationale="Run verification tests to confirm baseline or isolate error.",
                    )
                )

            # 3. Usage & Symbol Search
            if (
                probs.get("need_search", 0.0) >= threshold
                or probs.get("need_usage_search", 0.0) >= threshold
            ):
                if strategy == "GENERAL_INVESTIGATION":
                    strategy = (
                        "MAP_BLAST_RADIUS"
                        if probs.get("need_usage_search", 0.0) >= threshold
                        else "EXPAND_SEARCH"
                    )
                reasons.append(
                    "Symbol references and callers require repository discovery."
                )
                actions.append(
                    RecommendedAction(
                        action=ActionType.SEARCH_SYMBOL,
                        params={"query": request.user_goal, "file_pattern": "*.py"},
                        priority=1,
                        rationale="Search repository symbols and references matching goal.",
                    )
                )

            # 4. Source Inspection
            if probs.get("need_file_read", 0.0) >= threshold:
                if strategy == "GENERAL_INVESTIGATION":
                    strategy = "INSPECT_SOURCE"
                reasons.append(
                    f"File inspection indicated ({probs['need_file_read']:.2f}). Candidate files must be sliced."
                )
                extracted = StateSynthesizer.extract_file_paths(
                    "\n".join(request.collected_evidence)
                )
                candidate_files = [
                    f
                    for f in (request.known_files or extracted)
                    if not self.config.is_file_forbidden(f)
                ]
                actions.append(
                    RecommendedAction(
                        action=ActionType.READ_FILE_SLICE,
                        params={
                            "candidate_files": candidate_files[:4],
                            "focus_lines": f"1-{max_slice_lines}",
                        },
                        priority=2,
                        rationale="Inspect relevant file sections to verify behavior.",
                    )
                )

            # 5. Git Diff & History
            if (
                probs.get("need_git", 0.0) >= threshold
                or probs.get("need_git_blame", 0.0) >= threshold
            ):
                if strategy == "GENERAL_INVESTIGATION":
                    strategy = "INSPECT_GIT_HISTORY"
                actions.append(
                    RecommendedAction(
                        action=ActionType.GIT_DIFF,
                        params={
                            "target_files": request.modified_files
                            or request.known_files[:3]
                        },
                        priority=3,
                        rationale="Check recent commits and working tree status.",
                    )
                )

            # 6. Proceed with Modification / Fix
            if (
                probs.get("ready_to_fix", 0.0) >= threshold
                or probs.get("ready_to_edit", 0.0) >= threshold
            ):
                strategy = "PROCEED_WITH_MODIFICATION"
                target_files = [
                    f
                    for f in (request.known_files or ["src/"])
                    if not self.config.is_file_forbidden(f)
                ]
                actions.append(
                    RecommendedAction(
                        action=ActionType.PROCEED_WITH_EDIT,
                        params={
                            "target_files": target_files[:3],
                            "blast_radius_files": target_files,
                        },
                        priority=1,
                        rationale="Root cause confirmed and callers mapped. Proceed with precise code modifications.",
                    )
                )

            # Default fallback action
            if not actions:
                strategy = "GENERAL_INVESTIGATION"
                actions.append(
                    RecommendedAction(
                        action=ActionType.SEARCH_SYMBOL,
                        params={"query": request.user_goal},
                        priority=1,
                        rationale="Default investigation search.",
                    )
                )

            # Dynamic Prohibitions
            if not request.collected_evidence and not request.known_files:
                prohibited.append("do_not_edit_code_before_investigating_evidence")
            if (
                not probs.get("ready_to_fix", 0.0) >= threshold
                and category == TaskCategory.DEBUGGING
            ):
                prohibited.append("do_not_guess_fix_without_confirming_root_cause")
            if (
                probs.get("need_usage_search", 0.0) >= threshold
                and category == TaskCategory.REFACTORING
            ):
                prohibited.append("do_not_refactor_without_mapping_callers")
            if category == TaskCategory.TESTING and not is_sufficient:
                prohibited.append("verify_tests_before_declaring_done")
            if len(request.known_files) >= 2 and probs.get("need_search", 0.0) < 0.50:
                prohibited.append("avoid_broad_search_when_candidate_files_known")

        # Global Policy Guardrails
        for f in request.known_files + request.modified_files:
            if self.config.is_file_read_only(f) and category in (
                TaskCategory.DEBUGGING,
                TaskCategory.REFACTORING,
                TaskCategory.CODE_EDIT,
            ):
                prohibited.append(f"read_only_file_modification_prohibited:{f}")

        if self.config.policy.require_tests_before_edit and category in (
            TaskCategory.DEBUGGING,
            TaskCategory.REFACTORING,
            TaskCategory.CODE_EDIT,
        ):
            has_test_evidence = any(
                "test" in e.lower() or "passed" in e.lower() or "pytest" in e.lower()
                for e in request.collected_evidence
            )
            if not has_test_evidence:
                prohibited.append("do_not_edit_code_before_running_tests")

        if len(request.modified_files) > self.config.policy.blast_radius_limit:
            prohibited.append(
                f"blast_radius_limit_exceeded:{len(request.modified_files)}>{self.config.policy.blast_radius_limit}"
            )

        # Inject custom prohibitions from config
        for cp in self.config.policy.custom_prohibitions:
            if cp not in prohibited:
                prohibited.append(cp)

        confidence = max(probs.values()) if probs else 0.80

        return DecisionResponse(
            strategy=strategy,
            confidence=round(confidence, 3),
            recommended_actions=actions,
            prohibited_actions=list(dict.fromkeys(prohibited)),
            suggested_model_tier=tier,
            is_sufficient=is_sufficient,
            raw_probabilities={k: round(v, 3) for k, v in probs.items()},
            reasoning=" ".join(reasons)
            if reasons
            else f"Action routed via {category.value} matrix.",
        )
