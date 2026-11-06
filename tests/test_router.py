from codeprobe.core.router import LayaDecisionRouter
from codeprobe.schemas import (
    ActionType,
    DecisionRequest,
    ModelTier,
    TaskCategory,
)


def test_router_initial_investigation_routing():
    router = LayaDecisionRouter()
    req = DecisionRequest(
        user_goal="Find where user session token is generated",
        task_category=TaskCategory.INVESTIGATION,
        collected_evidence=[],
        known_files=[],
    )
    decision = router.route(req)
    assert decision.strategy in ("EXPAND_SEARCH", "GENERAL_INVESTIGATION")
    assert any(
        a.action == ActionType.SEARCH_SYMBOL for a in decision.recommended_actions
    )
    assert (
        "do_not_edit_code_before_investigating_evidence" in decision.prohibited_actions
    )
    assert decision.is_sufficient is False


def test_router_evidence_sufficient_routing():
    router = LayaDecisionRouter()
    req = DecisionRequest(
        user_goal="Find where user session token is generated",
        task_category=TaskCategory.INVESTIGATION,
        collected_evidence=[
            "=== SEARCH: token ===\nsrc/token.py:10:generate_token",
            "=== FILE: src/token.py ===\ndef generate_token(): return uuid4()",
            "=== TESTS ===\n5 passed in 0.1s",
        ],
        known_files=["src/token.py"],
        current_step=3,
    )
    decision = router.route(req)
    assert decision.is_sufficient is True
    assert decision.strategy == "READY_TO_SYNTHESIZE"
    assert any(
        a.action == ActionType.SYNTHESIZE_ANSWER for a in decision.recommended_actions
    )


def test_router_debugging_routing():
    router = LayaDecisionRouter()
    req = DecisionRequest(
        user_goal="Fix ZeroDivisionError in calculate_discount",
        task_category=TaskCategory.DEBUGGING,
        last_error="ZeroDivisionError: division by zero at discount.py:42",
        known_files=["src/discount.py"],
    )
    decision = router.route(req)
    assert decision.suggested_model_tier == ModelTier.REASONING_HEAVY
    assert any(
        a.action in (ActionType.READ_FILE_SLICE, ActionType.RUN_TESTS)
        for a in decision.recommended_actions
    )
