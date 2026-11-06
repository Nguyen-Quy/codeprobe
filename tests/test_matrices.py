from codeprobe.core.matrices import (
    DEBUGGING_MATRIX,
    INVESTIGATION_MATRIX,
    MATRICES,
    REFACTORING_MATRIX,
)
from codeprobe.core.router import LayaDecisionRouter
from codeprobe.schemas import (
    ActionType,
    DecisionRequest,
    ModelTier,
    TaskCategory,
)


def test_all_categories_in_matrices_registry():
    for cat in TaskCategory:
        assert cat in MATRICES
        assert MATRICES[cat].questions is not None
        assert len(MATRICES[cat].questions) > 0


def test_investigation_matrix_question_keys():
    expected_keys = {
        "need_search",
        "need_file_read",
        "need_git",
        "need_schema",
        "need_tests",
        "enough_evidence",
    }
    assert set(INVESTIGATION_MATRIX.questions.keys()) == expected_keys


def test_debugging_matrix_question_keys():
    expected_keys = {
        "need_reproduce",
        "need_trace_error",
        "need_git_blame",
        "ready_to_fix",
        "enough_evidence",
    }
    assert set(DEBUGGING_MATRIX.questions.keys()) == expected_keys


def test_refactoring_matrix_question_keys():
    expected_keys = {
        "need_usage_search",
        "need_test_coverage",
        "ready_to_edit",
        "enough_evidence",
    }
    assert set(REFACTORING_MATRIX.questions.keys()) == expected_keys


def test_testing_matrix_routing():
    router = LayaDecisionRouter()

    # Unverified state -> run tests
    req = DecisionRequest(
        user_goal="Verify if user session fix passes test suite",
        task_category=TaskCategory.TESTING,
        collected_evidence=[],
        known_files=["tests/test_session.py"],
    )
    decision = router.route(req)
    assert any(a.action == ActionType.RUN_TESTS for a in decision.recommended_actions)
    assert "verify_tests_before_declaring_done" in decision.prohibited_actions

    # Passing test evidence -> ready to synthesize
    req_passing = DecisionRequest(
        user_goal="Verify test suite",
        task_category=TaskCategory.TESTING,
        collected_evidence=["=== TESTS ===\n10 passed in 0.4s"],
        known_files=["tests/test_session.py"],
    )
    decision_passing = router.route(req_passing)
    assert decision_passing.is_sufficient is True
    assert decision_passing.strategy == "READY_TO_SYNTHESIZE"


def test_model_routing_matrix():
    router = LayaDecisionRouter()

    # Fast infer for simple lookup
    req_fast = DecisionRequest(
        user_goal="Grep for PORT variable in config",
        task_category=TaskCategory.MODEL_ROUTING,
    )
    res_fast = router.route(req_fast)
    assert res_fast.suggested_model_tier == ModelTier.FAST_INFER

    # Reasoning heavy for complex deadlock
    req_reasoning = DecisionRequest(
        user_goal="Solve complex deadlock in thread pool architecture",
        task_category=TaskCategory.MODEL_ROUTING,
    )
    res_reasoning = router.route(req_reasoning)
    assert res_reasoning.suggested_model_tier == ModelTier.REASONING_HEAVY


def test_rich_action_params():
    router = LayaDecisionRouter()
    req = DecisionRequest(
        user_goal="Fix IndexError in parse_header",
        task_category=TaskCategory.DEBUGGING,
        last_error="IndexError: list index out of range at http/parser.py:55",
        known_files=["http/parser.py"],
    )
    decision = router.route(req)
    slice_action = next(
        a
        for a in decision.recommended_actions
        if a.action == ActionType.READ_FILE_SLICE
    )
    assert "candidate_files" in slice_action.params
    assert "http/parser.py" in slice_action.params["candidate_files"]
    assert "focus_lines" in slice_action.params
