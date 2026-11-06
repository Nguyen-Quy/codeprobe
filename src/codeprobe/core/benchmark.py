from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..schemas import (
    ActionType,
    DecisionRequest,
    DecisionResponse,
    ModelTier,
    TaskCategory,
)
from .router import LayaDecisionRouter


@dataclass
class BenchmarkScenario:
    name: str
    description: str
    request: DecisionRequest
    expected_strategy: str | None = None
    expected_model_tier: ModelTier | None = None
    expected_action_type: ActionType | None = None
    expected_sufficient: bool | None = None
    validator: Callable[[DecisionResponse], bool] | None = None


@dataclass
class BenchmarkResult:
    scenario_name: str
    category: TaskCategory
    strategy: str
    confidence: float
    model_tier: ModelTier
    is_sufficient: bool
    passed: bool
    details: str = ""


STANDARD_SCENARIOS: list[BenchmarkScenario] = [
    BenchmarkScenario(
        name="Cold Investigation",
        description="Initial repository symbol discovery before any files or evidence are known",
        request=DecisionRequest(
            user_goal="Find where user session token is generated and stored",
            task_category=TaskCategory.INVESTIGATION,
            collected_evidence=[],
            known_files=[],
        ),
        expected_strategy="EXPAND_SEARCH",
        expected_model_tier=ModelTier.FAST_INFER,
        expected_action_type=ActionType.SEARCH_SYMBOL,
        expected_sufficient=False,
    ),
    BenchmarkScenario(
        name="Candidate File Slicing",
        description="Search yielded candidate files, now inspect file slices",
        request=DecisionRequest(
            user_goal="Find where user session token is generated",
            task_category=TaskCategory.INVESTIGATION,
            collected_evidence=[
                "=== SEARCH: token ===\nsrc/token.py:10:generate_token\nsrc/auth.py:50:verify_token"
            ],
            known_files=["src/token.py", "src/auth.py"],
            current_step=1,
        ),
        expected_strategy="INSPECT_SOURCE",
        expected_action_type=ActionType.READ_FILE_SLICE,
        expected_sufficient=False,
    ),
    BenchmarkScenario(
        name="Active Traceback Debugging",
        description="Bug report with stack trace requires error line inspection and reproduction",
        request=DecisionRequest(
            user_goal="Fix ZeroDivisionError in discount calculation",
            task_category=TaskCategory.DEBUGGING,
            last_error="ZeroDivisionError: division by zero at src/discount.py:42",
            known_files=["src/discount.py"],
        ),
        expected_strategy="TRACE_ERROR",
        expected_model_tier=ModelTier.REASONING_HEAVY,
        expected_action_type=ActionType.READ_FILE_SLICE,
        expected_sufficient=False,
    ),
    BenchmarkScenario(
        name="Refactoring Blast Radius Mapping",
        description="Refactoring critical interface requires searching all callers and usages first",
        request=DecisionRequest(
            user_goal="Refactor DatabaseConnection pool interface",
            task_category=TaskCategory.REFACTORING,
            collected_evidence=[],
            known_files=[],
        ),
        expected_strategy="MAP_BLAST_RADIUS",
        expected_model_tier=ModelTier.REASONING_HEAVY,
        expected_action_type=ActionType.SEARCH_SYMBOL,
        expected_sufficient=False,
    ),
    BenchmarkScenario(
        name="Test Suite Verification",
        description="Verify test suite execution status after modifications",
        request=DecisionRequest(
            user_goal="Run pytest verification suite for auth module",
            task_category=TaskCategory.TESTING,
            collected_evidence=["=== TESTS ===\n5 passed, 0 failed in 0.22s"],
            known_files=["tests/test_auth.py"],
        ),
        expected_strategy="READY_TO_SYNTHESIZE",
        expected_sufficient=True,
    ),
    BenchmarkScenario(
        name="Trivial Task Fast Model Routing",
        description="Simple symbol grep or regex lookup routes to fast infer tier",
        request=DecisionRequest(
            user_goal="Grep for API_KEY environment variable definition in config files",
            task_category=TaskCategory.MODEL_ROUTING,
        ),
        expected_model_tier=ModelTier.FAST_INFER,
        expected_sufficient=False,
    ),
    BenchmarkScenario(
        name="Complex Concurrency Reasoning Routing",
        description="Subtle race condition and deadlock analysis routes to reasoning heavy tier",
        request=DecisionRequest(
            user_goal="Diagnose distributed deadlock and race condition across worker threads",
            task_category=TaskCategory.MODEL_ROUTING,
        ),
        expected_model_tier=ModelTier.REASONING_HEAVY,
        expected_sufficient=False,
    ),
]


def run_matrix_benchmark(
    scenarios: list[BenchmarkScenario] | None = None,
    category_filter: TaskCategory | None = None,
) -> list[BenchmarkResult]:
    """
    Execute standard or custom scenarios against LayaDecisionRouter
    and validate decision assertions.
    """
    router = LayaDecisionRouter()
    active_scenarios = scenarios or STANDARD_SCENARIOS
    if category_filter:
        active_scenarios = [
            s for s in active_scenarios if s.request.task_category == category_filter
        ]

    results: list[BenchmarkResult] = []

    for scenario in active_scenarios:
        decision = router.route(scenario.request)
        passed = True
        failures: list[str] = []

        if (
            scenario.expected_strategy
            and decision.strategy != scenario.expected_strategy
        ):
            passed = False
            failures.append(
                f"strategy expected {scenario.expected_strategy!r} got {decision.strategy!r}"
            )

        if (
            scenario.expected_model_tier
            and decision.suggested_model_tier != scenario.expected_model_tier
        ):
            passed = False
            failures.append(
                f"model_tier expected {scenario.expected_model_tier.value!r} got {decision.suggested_model_tier.value!r}"
            )

        if (
            scenario.expected_sufficient is not None
            and decision.is_sufficient != scenario.expected_sufficient
        ):
            passed = False
            failures.append(
                f"is_sufficient expected {scenario.expected_sufficient} got {decision.is_sufficient}"
            )

        if scenario.expected_action_type:
            action_types = [a.action for a in decision.recommended_actions]
            if scenario.expected_action_type not in action_types:
                passed = False
                failures.append(
                    f"action_type {scenario.expected_action_type.value!r} not in {action_types}"
                )

        if scenario.validator and not scenario.validator(decision):
            passed = False
            failures.append("custom validator failed")

        category = scenario.request.task_category or TaskCategory.GENERAL
        results.append(
            BenchmarkResult(
                scenario_name=scenario.name,
                category=category,
                strategy=decision.strategy,
                confidence=decision.confidence,
                model_tier=decision.suggested_model_tier,
                is_sufficient=decision.is_sufficient,
                passed=passed,
                details="; ".join(failures) if failures else "OK",
            )
        )

    return results


def format_benchmark_table(results: list[BenchmarkResult]) -> str:
    """
    Render benchmark results into a clean ASCII table.
    """
    headers = ["Scenario", "Category", "Strategy", "Tier", "Conf", "Status"]
    rows = []
    for r in results:
        status = "PASSED" if r.passed else "FAILED"
        rows.append(
            [
                r.scenario_name[:32],
                r.category.value,
                r.strategy,
                r.model_tier.value,
                f"{r.confidence:.2f}",
                status,
            ]
        )

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(val))

    separator = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    header_line = (
        "| " + " | ".join(f"{h:<{w}}" for h, w in zip(headers, col_widths)) + " |"
    )

    lines = [separator, header_line, separator]
    for row in rows:
        line = (
            "| " + " | ".join(f"{val:<{w}}" for val, w in zip(row, col_widths)) + " |"
        )
        lines.append(line)
    lines.append(separator)

    passed_count = sum(1 for r in results if r.passed)
    total_count = len(results)
    lines.append(f"\nSummary: {passed_count}/{total_count} benchmark scenarios passed.")
    return "\n".join(lines)
