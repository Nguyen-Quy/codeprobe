from codeprobe.config import GuardrailsConfig, PolicyConfig, ProjectConfig
from codeprobe.core.router import LayaDecisionRouter
from codeprobe.schemas import ActionType, DecisionRequest, TaskCategory


def test_guardrails_forbidden_files_filtering():
    custom_cfg = ProjectConfig(
        guardrails=GuardrailsConfig(
            forbidden_files=[".env*", "*.pem", "secrets/*"],
        ),
    )
    router = LayaDecisionRouter(config=custom_cfg)

    req = DecisionRequest(
        user_goal="Check secret token in environment and server key",
        task_category=TaskCategory.INVESTIGATION,
        collected_evidence=[
            "=== SEARCH ===\n.env:1:SECRET_KEY=12345\nserver.pem:1:CERT\nsrc/app.py:10:run",
        ],
        known_files=[".env", "server.pem", "src/app.py"],
    )

    decision = router.route(req)

    # Check that forbidden files triggered prohibitions
    assert any("forbidden_file_access:.env" in p for p in decision.prohibited_actions)
    assert any(
        "forbidden_file_access:server.pem" in p for p in decision.prohibited_actions
    )

    # Check that candidate files for slice only include non-forbidden files
    for action in decision.recommended_actions:
        if action.action == ActionType.READ_FILE_SLICE:
            candidates = action.params.get("candidate_files", [])
            assert ".env" not in candidates
            assert "server.pem" not in candidates


def test_guardrails_read_only_files_prohibition():
    custom_cfg = ProjectConfig(
        guardrails=GuardrailsConfig(
            read_only_files=["package-lock.json", "poetry.lock"],
        ),
        policy=PolicyConfig(
            require_tests_before_edit=False,
        ),
    )
    router = LayaDecisionRouter(config=custom_cfg)

    # Ready to edit with package-lock.json in known_files
    req = DecisionRequest(
        user_goal="Update dependencies in lockfile",
        task_category=TaskCategory.CODE_EDIT,
        collected_evidence=[
            "=== FILE ===\npackage-lock.json content",
            "=== FILE ===\npackage.json content",
        ],
        known_files=["package-lock.json", "src/index.js"],
    )

    decision = router.route(req)
    assert any(
        "read_only_file_modification_prohibited:package-lock.json" in p
        for p in decision.prohibited_actions
    )


def test_guardrails_require_tests_before_edit():
    custom_cfg = ProjectConfig(
        policy=PolicyConfig(
            require_tests_before_edit=True,
        ),
    )
    router = LayaDecisionRouter(config=custom_cfg)

    # Ready to edit but no test evidence gathered
    req = DecisionRequest(
        user_goal="Fix bug in calculate_total",
        task_category=TaskCategory.DEBUGGING,
        collected_evidence=[
            "=== FILE ===\nsrc/calc.py:def calculate_total(): ...",
            "=== SEARCH ===\nFound calculate_total",
        ],
        known_files=["src/calc.py"],
    )

    decision = router.route(req)
    assert "do_not_edit_code_before_running_tests" in decision.prohibited_actions


def test_guardrails_blast_radius_limit():
    custom_cfg = ProjectConfig(
        policy=PolicyConfig(
            blast_radius_limit=2,
        ),
    )
    router = LayaDecisionRouter(config=custom_cfg)

    req = DecisionRequest(
        user_goal="Refactor service layer across multiple files",
        task_category=TaskCategory.REFACTORING,
        modified_files=["src/a.py", "src/b.py", "src/c.py", "src/d.py"],
    )

    decision = router.route(req)
    assert any("blast_radius_limit_exceeded" in p for p in decision.prohibited_actions)
