from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from codeprobe.core.declarations import DeclarationUnit
from codeprobe.core.recon import (
    ContextSufficiencyEvaluator,
    GoalDecomposer,
    GoalIntent,
    MultiHopReconEngine,
)


def test_goal_decomposer_code_logic():
    query = "Find where calculate_total and UserAuthMiddleware handle discounts"
    decomposed = GoalDecomposer.decompose(query)

    assert decomposed.intent == GoalIntent.CODE_LOGIC
    assert "calculate_total" in decomposed.primary_symbols
    assert "UserAuthMiddleware" in decomposed.primary_symbols
    assert not decomposed.is_scaffold


def test_goal_decomposer_error_trace():
    query = "Traceback (most recent call last): TypeError: unsupported operand in db_session.py"
    decomposed = GoalDecomposer.decompose(query)

    assert decomposed.intent == GoalIntent.ERROR_TRACE
    assert "TypeError" in decomposed.error_tokens


def test_goal_decomposer_infra():
    query = (
        "Check Kubernetes NetworkPolicy ingress rules and postgres Service in deploy/"
    )
    decomposed = GoalDecomposer.decompose(query)

    assert decomposed.intent == GoalIntent.INFRA_CONFIG


def test_goal_decomposer_scaffold():
    query = "Thêm endpoint mới /api/v1/refunds và tạo mới RefundService trong app"
    decomposed = GoalDecomposer.decompose(query)

    assert decomposed.intent == GoalIntent.NEW_FEATURE_SCAFFOLD
    assert decomposed.is_scaffold is True
    assert "RefundService" in decomposed.primary_symbols


def test_goal_decomposer_env_vars():
    query = "Fix database connection timeout with DATABASE_URL and REDIS_CACHE_PORT"
    decomposed = GoalDecomposer.decompose(query)

    assert "DATABASE_URL" in decomposed.env_var_tokens
    assert "REDIS_CACHE_PORT" in decomposed.env_var_tokens


def test_sufficiency_evaluator_code_logic_complete():
    decomposed = GoalDecomposer.decompose("Fix bug in verify_jwt")
    candidate_files = ["src/auth/jwt.py"]
    declarations = [
        DeclarationUnit(
            name="verify_jwt",
            kind="function",
            file_path="src/auth/jwt.py",
            start_line=10,
            end_line=25,
            signature="def verify_jwt(token: str):",
            calls=["decode"],
        )
    ]
    cross_file_links = ["handle_login (src/api.py) -> verify_jwt (src/auth/jwt.py)"]

    score = ContextSufficiencyEvaluator.evaluate(
        decomposed=decomposed,
        candidate_files=candidate_files,
        declarations=declarations,
        cross_file_links=cross_file_links,
        discovered_env_vars=set(),
        found_config_files=[],
    )

    assert score.target_file_score == 0.30
    assert score.anchor_code_score == 0.30
    assert score.callers_score == 0.20
    assert score.config_score == 0.20
    assert score.total_score == 1.0
    assert score.is_sufficient is True
    assert len(score.missing_aspects) == 0


def test_sufficiency_evaluator_missing_anchor():
    decomposed = GoalDecomposer.decompose("Fix bug in verify_jwt")
    candidate_files = ["src/auth/jwt.py"]
    # Declarations empty or no exact line numbers
    declarations = []

    score = ContextSufficiencyEvaluator.evaluate(
        decomposed=decomposed,
        candidate_files=candidate_files,
        declarations=declarations,
        cross_file_links=[],
        discovered_env_vars=set(),
        found_config_files=[],
    )

    assert score.anchor_code_score == 0.0
    assert "code_anchor" in score.missing_aspects
    assert score.total_score < 0.80
    assert score.is_sufficient is False


def test_sufficiency_evaluator_new_feature_scaffold(tmp_path: Path):
    decomposed = GoalDecomposer.decompose(
        "Thêm mới RefundController và đăng ký endpoint"
    )
    candidate_files = ["src/routes.py", "src/controllers/payment.py"]

    score = ContextSufficiencyEvaluator.evaluate(
        decomposed=decomposed,
        candidate_files=candidate_files,
        declarations=[],
        cross_file_links=[],
        discovered_env_vars=set(),
        found_config_files=[],
    )

    # Dual anchor: mounting point + exemplar donor
    assert score.mounting_point == "src/routes.py"
    assert score.exemplar_file == "src/controllers/payment.py"
    assert score.target_file_score == 0.30
    assert score.anchor_code_score == 0.30
    assert score.total_score >= 0.80
    assert score.is_sufficient is True


def test_multi_hop_recon_engine_execution(tmp_path: Path):
    # Setup files
    auth_dir = tmp_path / "src" / "auth"
    auth_dir.mkdir(parents=True)
    auth_file = auth_dir / "service.py"
    auth_file.write_text(
        """
import os

class AuthService:
    def login(self, username, password):
        secret = os.environ.get("AUTH_SECRET_KEY")
        return True
""",
        encoding="utf-8",
    )

    api_dir = tmp_path / "src" / "api"
    api_dir.mkdir(parents=True)
    api_file = api_dir / "routes.py"
    api_file.write_text(
        """
from src.auth.service import AuthService

def handle_login():
    auth = AuthService()
    return auth.login("u", "p")
""",
        encoding="utf-8",
    )

    config_file = tmp_path / ".env"
    config_file.write_text("AUTH_SECRET_KEY=supersecret123\n", encoding="utf-8")

    # Mock HierarchicalExplorer that returns candidates per query
    mock_explorer = MagicMock()

    def fake_explore(query: str):
        if "login" in query or "AuthService" in query:
            return ["src/auth/service.py"], False
        elif "routes" in query or "caller" in query or "AuthService" in query:
            return ["src/api/routes.py"], False
        elif "SECRET" in query or "env" in query:
            return [".env"], False
        return ["src/auth/service.py", "src/api/routes.py"], False

    mock_explorer.explore.side_effect = fake_explore

    engine = MultiHopReconEngine(workspace_root=tmp_path)
    report = engine.run(
        query="Where is user login handled in AuthService and what config does it use?",
        hierarchical_explorer=mock_explorer,
        max_hops=6,
        threshold=0.80,
    )

    assert report.final_score.is_sufficient is True
    assert report.final_score.total_score >= 0.80
    assert len(report.hops) >= 1
    assert any("AuthService" in d.name for d in report.declarations)
