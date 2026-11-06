from codeprobe.schemas import (
    ActionType,
    DecisionRequest,
    DecisionResponse,
    ModelTier,
    RecommendedAction,
    TaskCategory,
)


def test_decision_request_serialization():
    req = DecisionRequest(
        user_goal="Find root cause of User authentication timeout in auth.py",
        task_category=TaskCategory.DEBUGGING,
        current_step=1,
        collected_evidence=["=== SEARCH: auth ===\nsrc/auth.py:45:def authenticate():"],
        known_files=["src/auth.py"],
        last_error="TimeoutError: database lock held too long",
    )
    data = req.model_dump()
    assert data["task_category"] == "debugging"
    assert data["known_files"] == ["src/auth.py"]
    assert "TimeoutError" in data["last_error"]

    json_str = req.model_dump_json()
    parsed = DecisionRequest.model_validate_json(json_str)
    assert parsed.user_goal == req.user_goal
    assert parsed.task_category == TaskCategory.DEBUGGING


def test_decision_response_serialization():
    resp = DecisionResponse(
        strategy="INSPECT_SOURCE",
        confidence=0.88,
        recommended_actions=[
            RecommendedAction(
                action=ActionType.READ_FILE_SLICE,
                params={"candidate_files": ["src/auth.py"]},
                priority=1,
                rationale="Inspect authenticate function implementation",
            )
        ],
        prohibited_actions=["do_not_edit_without_tests"],
        suggested_model_tier=ModelTier.REASONING_HEAVY,
        is_sufficient=False,
        raw_probabilities={"need_file_read": 0.92, "need_search": 0.25},
        reasoning="Authentication error points directly to src/auth.py",
    )
    json_str = resp.model_dump_json()
    parsed = DecisionResponse.model_validate_json(json_str)
    assert parsed.strategy == "INSPECT_SOURCE"
    assert len(parsed.recommended_actions) == 1
    assert parsed.recommended_actions[0].action == ActionType.READ_FILE_SLICE
    assert parsed.suggested_model_tier == ModelTier.REASONING_HEAVY
