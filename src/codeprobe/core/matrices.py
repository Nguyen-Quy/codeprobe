from __future__ import annotations

from dataclasses import dataclass, field

from ..schemas import TaskCategory


@dataclass
class DecisionMatrix:
    category: TaskCategory
    description: str
    questions: dict[str, dict[str, str]] = field(default_factory=dict)


INVESTIGATION_MATRIX = DecisionMatrix(
    category=TaskCategory.INVESTIGATION,
    description="Questions for codebase exploration and evidence collection",
    questions={
        "need_search": {
            "type": "noul",
            "instructions": "Does the task need another repository search (ripgrep/symbol search) before reading files?",
        },
        "need_file_read": {
            "type": "noul",
            "instructions": "Are there candidate source files in the evidence that must be read or sliced?",
        },
        "need_git": {
            "type": "noul",
            "instructions": "Would git status, git diff, or git log provide valuable missing context?",
        },
        "need_schema": {
            "type": "noul",
            "instructions": "Does the task specifically require inspecting models, database schemas, or API contracts?",
        },
        "need_tests": {
            "type": "noul",
            "instructions": "Should existing test suites or validation commands be executed to gather evidence?",
        },
        "enough_evidence": {
            "type": "noul",
            "instructions": "Is there already enough repository evidence to answer the question or conclude?",
        },
    },
)

DEBUGGING_MATRIX = DecisionMatrix(
    category=TaskCategory.DEBUGGING,
    description="Questions for diagnosing bugs, errors, and test failures",
    questions={
        "need_reproduce": {
            "type": "noul",
            "instructions": "Should the agent execute tests or run a command to reproduce the error first?",
        },
        "need_trace_error": {
            "type": "noul",
            "instructions": "Does the stack trace or error message point to specific source files that must be read?",
        },
        "need_git_blame": {
            "type": "noul",
            "instructions": "Would checking recent git history/diff reveal the regression source?",
        },
        "ready_to_fix": {
            "type": "noul",
            "instructions": "Is the root cause definitively identified and verified so code editing can proceed?",
        },
        "enough_evidence": {
            "type": "noul",
            "instructions": "Is there enough information to diagnose the issue without further search?",
        },
    },
)

REFACTORING_MATRIX = DecisionMatrix(
    category=TaskCategory.REFACTORING,
    description="Questions for safe code modifications, restructuring, and cleanup",
    questions={
        "need_usage_search": {
            "type": "noul",
            "instructions": "Must all symbol usages and callers across the repo be searched before editing?",
        },
        "need_test_coverage": {
            "type": "noul",
            "instructions": "Does test coverage need to be verified or added before refactoring?",
        },
        "ready_to_edit": {
            "type": "noul",
            "instructions": "Have all dependencies and blast radiuses been mapped, making it safe to proceed with edit?",
        },
        "enough_evidence": {
            "type": "noul",
            "instructions": "Has sufficient blast radius analysis been completed to proceed with edits or review?",
        },
    },
)

TESTING_MATRIX = DecisionMatrix(
    category=TaskCategory.TESTING,
    description="Questions for test execution, coverage gap analysis, and verification",
    questions={
        "need_run_existing": {
            "type": "noul",
            "instructions": "Should the current test suite or target test file be executed first?",
        },
        "need_new_test": {
            "type": "noul",
            "instructions": "Does this task require writing new test cases or expanding edge case coverage?",
        },
        "need_regression_check": {
            "type": "noul",
            "instructions": "Must the full test suite be run to ensure no regressions in related modules?",
        },
        "tests_passing": {
            "type": "noul",
            "instructions": "Have all relevant test suites passed with green status?",
        },
        "enough_evidence": {
            "type": "noul",
            "instructions": "Is verification complete and test assertions proven sufficient?",
        },
    },
)

MODEL_ROUTING_MATRIX = DecisionMatrix(
    category=TaskCategory.MODEL_ROUTING,
    description="Questions for selecting the optimal model tier and compute allocation",
    questions={
        "is_trivial_task": {
            "type": "noul",
            "instructions": "Is this a straightforward lookup, regex search, single-file reading, or minor edit suitable for a fast/cheap model?",
        },
        "standard_coding": {
            "type": "noul",
            "instructions": "Is this standard feature implementation, routine bug fix, or standard PR task suitable for a standard frontier model?",
        },
        "requires_deep_reasoning": {
            "type": "noul",
            "instructions": "Does this task require complex architectural analysis, multi-component refactoring, or subtle bug diagnosis needing frontier reasoning?",
        },
    },
)

MATRICES: dict[TaskCategory, DecisionMatrix] = {
    TaskCategory.INVESTIGATION: INVESTIGATION_MATRIX,
    TaskCategory.DEBUGGING: DEBUGGING_MATRIX,
    TaskCategory.REFACTORING: REFACTORING_MATRIX,
    TaskCategory.CODE_EDIT: REFACTORING_MATRIX,
    TaskCategory.TESTING: TESTING_MATRIX,
    TaskCategory.MODEL_ROUTING: MODEL_ROUTING_MATRIX,
    TaskCategory.GENERAL: INVESTIGATION_MATRIX,
}
