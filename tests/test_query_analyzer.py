from __future__ import annotations

from codeprobe.core.query_analyzer import (
    PreFlightQueryAnalyzer,
    QueryStatus,
)
from codeprobe.executor import Investigator
from codeprobe.schemas import QueryDomain


def test_ambiguous_queries_trigger_clarification():
    analyzer = PreFlightQueryAnalyzer()

    # Vague English
    res1 = analyzer.analyze("fix this")
    assert res1.status == QueryStatus.NEEDS_CLARIFICATION
    assert len(res1.clarification_questions) > 0

    res2 = analyzer.analyze("check code")
    assert res2.status == QueryStatus.NEEDS_CLARIFICATION

    # Vague Vietnamese
    res3 = analyzer.analyze("sửa lỗi đi")
    assert res3.status == QueryStatus.NEEDS_CLARIFICATION

    res4 = analyzer.analyze("có lỗi gì không?")
    assert res4.status == QueryStatus.NEEDS_CLARIFICATION


def test_valid_queries_pass_and_extract_metadata():
    analyzer = PreFlightQueryAnalyzer()

    # Code logic query with concrete symbol
    res = analyzer.analyze("Where is handle_payment defined in PaymentService?")
    assert res.status == QueryStatus.VALID
    assert "handle_payment" in res.target_symbols or "PaymentService" in res.target_symbols
    assert res.domain == QueryDomain.APPLICATION_LOGIC

    # Infra query
    res_infra = analyzer.analyze("Review docker-compose and k8s backup deployment")
    assert res_infra.status == QueryStatus.VALID
    assert res_infra.domain == QueryDomain.INFRA_DEVOPS


def test_investigator_step0_ambiguity_early_exit(tmp_path):
    # Setup dummy workspace
    (tmp_path / "app.py").write_text("print('hello')", encoding="utf-8")

    investigator = Investigator()
    result = investigator.explore("fix this", workspace_path=str(tmp_path))

    assert result.needs_clarification is True
    assert result.strategy == "NEEDS_CLARIFICATION"
    assert len(result.clarification_questions) > 0
    assert result.examined_files == []
    assert "Clarification Needed" in result.summary

