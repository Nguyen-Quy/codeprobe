from codeprobe.core.benchmark import (
    STANDARD_SCENARIOS,
    format_benchmark_table,
    run_matrix_benchmark,
)
from codeprobe.schemas import TaskCategory


def test_standard_benchmark_execution():
    results = run_matrix_benchmark()
    assert len(results) == len(STANDARD_SCENARIOS)
    assert all(r.passed for r in results)


def test_benchmark_category_filter():
    results_debug = run_matrix_benchmark(category_filter=TaskCategory.DEBUGGING)
    assert len(results_debug) >= 1
    assert all(r.category == TaskCategory.DEBUGGING for r in results_debug)
    assert all(r.passed for r in results_debug)


def test_benchmark_table_formatting():
    results = run_matrix_benchmark()
    table = format_benchmark_table(results)
    assert "Scenario" in table
    assert "Category" in table
    assert "Strategy" in table
    assert "Summary: 7/7 benchmark scenarios passed." in table
