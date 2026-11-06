from __future__ import annotations

from unittest.mock import patch

from codeprobe.core.mid_flight import MidFlightAnalyst
from codeprobe.core.recon import (
    DecomposedGoal,
    GoalIntent,
    MultiHopReconEngine,
    SufficiencyScore,
)
from codeprobe.schemas import QueryDomain


def test_mid_flight_analyst_returns_clean_query():
    analyst = MidFlightAnalyst()

    with patch("codeprobe.core.mid_flight.chat", return_value="handle_payment stripe"):
        res = analyst.suggest_next_hop_query(
            query="Where is payment processed?",
            missing_aspects=["callers_and_breaking_changes"],
            examined_files=["src/billing/service.py"],
            discovered_symbols=["PaymentService"],
        )
        assert res == "handle_payment stripe"


def test_mid_flight_analyst_rejects_verbose_output():
    analyst = MidFlightAnalyst()

    with patch(
        "codeprobe.core.mid_flight.chat",
        return_value="This is a very long sentence that explains what you should search instead of returning a compact query string.",
    ):
        res = analyst.suggest_next_hop_query(
            query="Where is payment processed?",
            missing_aspects=["callers_and_breaking_changes"],
            examined_files=[],
            discovered_symbols=[],
        )
        assert res is None


def test_recon_engine_uses_mid_flight_analyst(tmp_path):
    engine = MultiHopReconEngine(workspace_root=tmp_path)
    decomposed = DecomposedGoal(
        original_query="find billing service",
        intent=GoalIntent.CODE_LOGIC,
        domain=QueryDomain.APPLICATION_LOGIC,
    )
    score = SufficiencyScore(
        target_file_score=0.3,
        anchor_code_score=0.0,
        callers_score=0.0,
        config_score=0.0,
        total_score=0.3,
        is_sufficient=False,
        missing_aspects=["code_anchor_or_definitions"],
    )

    with patch("codeprobe.core.mid_flight.chat", return_value="billing_engine process"):
        next_query = engine._generate_next_query(
            decomposed=decomposed,
            score=score,
            declarations=[],
            discovered_env_vars=set(),
            visited_symbols=set(),
            accumulated_files=[],
        )
        assert next_query == "billing_engine process"

