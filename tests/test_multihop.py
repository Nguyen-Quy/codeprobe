from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from codeprobe.cli import main
from codeprobe.executor import Investigator


def test_multihop_end_to_end_resolution(tmp_path: Path):
    # Setup test workspace
    src_dir = tmp_path / "src"
    billing_dir = src_dir / "billing"
    billing_dir.mkdir(parents=True)

    # 1. Billing Service with env var access
    service_file = billing_dir / "service.py"
    service_file.write_text(
        """import os

class PaymentService:
    def handle_payment(self, amount: float) -> bool:
        api_key = os.environ.get("STRIPE_SECRET_KEY")
        if not api_key:
            raise ValueError("Missing STRIPE_SECRET_KEY")
        return True
""",
        encoding="utf-8",
    )

    # 2. Main Entrypoint calling billing service
    main_file = src_dir / "main.py"
    main_file.write_text(
        """from src.billing.service import PaymentService

def main():
    service = PaymentService()
    return service.handle_payment(100.0)
""",
        encoding="utf-8",
    )

    # 3. Environment configuration
    env_file = tmp_path / ".env"
    env_file.write_text("STRIPE_SECRET_KEY=sk_test_fake_key_999\n", encoding="utf-8")

    investigator = Investigator()
    result = investigator.explore(
        query="Where is payment processed in PaymentService and what Stripe secret key is used?",
        workspace_path=str(tmp_path),
        max_steps=5,
    )

    assert result.is_sufficient is True
    assert result.sufficiency_score >= 0.80
    assert result.hop_count >= 1
    assert any("service.py" in f for f in result.examined_files)
    assert any(
        "PaymentService" in sym or "handle_payment" in sym
        for sym in result.discovered_symbols
    )
    assert result.summary != ""
    assert "Reconnaissance & Context Sufficiency" in result.summary


def test_multihop_early_exit_on_sufficiency(tmp_path: Path):
    # Setup a self-contained health check module
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    health_file = src_dir / "health.py"
    health_file.write_text(
        """class HealthChecker:
    def check(self) -> dict:
        return {"status": "ok"}
""",
        encoding="utf-8",
    )

    investigator = Investigator()
    result = investigator.explore(
        query="Inspect HealthChecker in health.py",
        workspace_path=str(tmp_path),
        max_steps=6,
    )

    assert result.is_sufficient is True
    assert result.sufficiency_score >= 0.80
    # Should early-exit within 1-2 hops instead of using all 6 hops
    assert result.hop_count <= 2
    assert any("health.py" in f for f in result.examined_files)


def test_multihop_max_hops_ceiling(tmp_path: Path):
    # Setup chained files
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    for i in range(10):
        (src_dir / f"mod_{i}.py").write_text(
            f"def func_{i}(): pass\n", encoding="utf-8"
        )

    investigator = Investigator()
    result = investigator.explore(
        query="Find unknown deep symbol nonexistent_in_repo",
        workspace_path=str(tmp_path),
        max_steps=10,  # Request 10 steps
    )

    # Max hops should never exceed 6
    assert result.hop_count <= 6


def test_multihop_new_feature_scaffold_dual_anchors(tmp_path: Path):
    # Setup workspace with routing entrypoint and controller exemplar
    routes_dir = tmp_path / "src" / "api"
    routes_dir.mkdir(parents=True)
    routes_file = routes_dir / "routes.py"
    routes_file.write_text(
        """from fastapi import APIRouter
router = APIRouter()
""",
        encoding="utf-8",
    )

    ctrl_dir = tmp_path / "src" / "controllers"
    ctrl_dir.mkdir(parents=True)
    ctrl_file = ctrl_dir / "user_controller.py"
    ctrl_file.write_text(
        """class UserController:
    def get_user(self, user_id: str):
        return {"id": user_id}
""",
        encoding="utf-8",
    )

    investigator = Investigator()
    result = investigator.explore(
        query="Thêm endpoint mới /api/v1/invoices và tạo InvoiceController mới trong app",
        workspace_path=str(tmp_path),
        max_steps=4,
    )

    assert result.strategy == "NEW_FEATURE_SCAFFOLD"
    assert result.mounting_point is not None
    assert "routes" in result.mounting_point
    assert result.exemplar_file is not None
    assert "controller" in result.exemplar_file
    assert result.is_sufficient is True
    assert result.sufficiency_score >= 0.80


def test_multihop_cli_investigate_output(tmp_path: Path, capsys):
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    auth_file = src_dir / "auth.py"
    auth_file.write_text(
        """def authenticate_user(token: str) -> bool:
    return token == "valid"
""",
        encoding="utf-8",
    )

    test_args = [
        "codeprobe",
        "investigate",
        "authenticate_user in auth.py",
    ]
    with patch("codeprobe.tools.ROOT", tmp_path), patch.object(sys, "argv", test_args):
        main()

    captured = capsys.readouterr()
    assert "CodeProbe Autonomous Investigation" in captured.out
    assert "Sufficiency:" in captured.out
    assert "Hops:" in captured.out
    assert "auth.py" in captured.out
