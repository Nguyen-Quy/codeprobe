from __future__ import annotations

from pathlib import Path

from codeprobe.extractor import QueryKeywordExtractor


def test_keyword_extractor_phase_and_planning():
    query = "Check progress and summary of phase 12.1 in .planning and roadmap"
    tokens = QueryKeywordExtractor.extract_search_tokens(query)

    # Should extract phase number, roadmap, planning
    assert any("12.1" in t for t in tokens)
    assert any("roadmap" in t.lower() for t in tokens)


def test_keyword_extractor_vietnamese_stopwords():
    query = "phase 12.1 làm tới đâu rồi? sao ko thấy summary?"
    tokens = QueryKeywordExtractor.extract_search_tokens(query)

    # Should eliminate Vietnamese stopwords like "làm", "tới", "đâu", "rồi", "sao", "ko", "thấy"
    for sw in ["làm", "tới", "đâu", "rồi", "sao", "ko", "thấy"]:
        assert sw not in tokens

    # Should retain 12.1
    assert any("12.1" in t for t in tokens)


def test_keyword_extractor_code_symbols_and_errors():
    query = (
        "TypeError: unsupported operand type in calculate_total and UserAuthMiddleware"
    )
    tokens = QueryKeywordExtractor.extract_search_tokens(query)

    assert "TypeError" in tokens
    assert "calculate_total" in tokens
    assert "UserAuthMiddleware" in tokens


def test_discover_workspace_paths(tmp_path: Path):
    planning = tmp_path / ".planning" / "phases" / "12.1-test"
    planning.mkdir(parents=True)
    plan_file = planning / "12.1-PLAN.md"
    plan_file.write_text("Wave 1 tasks")

    discovered = QueryKeywordExtractor.discover_workspace_paths(
        "check phase 12.1 progress", tmp_path
    )
    assert any("12.1-PLAN.md" in p for p in discovered)
