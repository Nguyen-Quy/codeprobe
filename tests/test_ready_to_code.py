from __future__ import annotations

import time
from pathlib import Path

from codeprobe.core.declarations import DeclarationUnit
from codeprobe.core.recon import (
    DecomposedGoal,
    GoalIntent,
    ReconReport,
    SufficiencyScore,
)
from codeprobe.core.relationships import RelationshipLink, RelationshipReport
from codeprobe.core.synthesizer import ReadyToCodeSynthesizer
from codeprobe.executor import Investigator
from codeprobe.schemas import ReadyToCodePayload
from codeprobe.tools import set_workspace_root


def test_ready_to_code_single_python_target(tmp_path: Path):
    src_file = tmp_path / "service.py"
    code = """import os

class PaymentService:
    def process(self, amount: int):
        return amount * 100
"""
    src_file.write_text(code, encoding="utf-8")

    decl = DeclarationUnit(
        name="PaymentService",
        kind="class",
        file_path="service.py",
        start_line=3,
        end_line=5,
        signature="class PaymentService:",
        body_snippet="class PaymentService:\n    def process(self, amount: int):\n        return amount * 100",
    )

    payload = ReadyToCodeSynthesizer.synthesize(
        query="Refactor PaymentService process method",
        examined_files=["service.py"],
        declarations=[decl],
        workspace_root=tmp_path,
    )

    assert payload is not None
    assert isinstance(payload, ReadyToCodePayload)
    assert len(payload.targets) >= 1

    primary = payload.targets[0]
    assert primary.file_path == "service.py"
    assert primary.role == "primary_source"
    assert primary.start_line == 3
    assert primary.end_line == 5
    assert "class PaymentService" in primary.current_code
    assert primary.target_content == primary.current_code
    assert "# Ready-to-Code:" not in primary.replacement_content
    assert primary.replacement_content == primary.current_code
    assert primary.diff_preview == ""


def test_ready_to_code_multi_target_cross_boundary(tmp_path: Path):
    # 1. Python source
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    py_file = src_dir / "worker.py"
    py_code = """import os

def run_worker():
    broker = os.environ.get("REDIS_BROKER_URL")
    return broker
"""
    py_file.write_text(py_code, encoding="utf-8")

    # 2. .env file
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=production\n", encoding="utf-8")

    # 3. Docker Compose
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        """version: '3.8'
services:
  worker:
    image: worker:latest
    environment:
      - APP_ENV=production
""",
        encoding="utf-8",
    )

    decl = DeclarationUnit(
        name="run_worker",
        kind="function",
        file_path="src/worker.py",
        start_line=3,
        end_line=5,
        signature="def run_worker():",
        body_snippet="def run_worker():\n    broker = os.environ.get('REDIS_BROKER_URL')\n    return broker",
        calls=["REDIS_BROKER_URL"],
    )

    decomposed = DecomposedGoal(
        original_query="Add REDIS_BROKER_URL support across worker and infra",
        intent=GoalIntent.INFRA_CONFIG,
    )
    score = SufficiencyScore(
        target_file_score=0.9,
        anchor_code_score=0.9,
        callers_score=0.8,
        config_score=0.8,
        total_score=0.85,
    )
    recon_report = ReconReport(
        query="Add REDIS_BROKER_URL support across worker and infra",
        decomposed=decomposed,
        final_score=score,
        env_vars={"REDIS_BROKER_URL"},
        config_files=[".env", "docker-compose.yml"],
    )

    payload = ReadyToCodeSynthesizer.synthesize(
        query="Add REDIS_BROKER_URL support across worker and infra",
        examined_files=["src/worker.py", ".env", "docker-compose.yml"],
        declarations=[decl],
        recon_report=recon_report,
        workspace_root=tmp_path,
    )

    assert payload is not None
    assert len(payload.targets) == 3

    roles = {t.role for t in payload.targets}
    assert "primary_source" in roles
    assert "config_binding" in roles
    assert "infra_manifest" in roles

    files = [t.file_path for t in payload.targets]
    assert "src/worker.py" in files
    assert ".env" in files
    assert "docker-compose.yml" in files


def test_ready_to_code_scaffold_target(tmp_path: Path):
    router_file = tmp_path / "router.py"
    router_file.write_text(
        """# Main router
def register_routes(app):
    app.add_route("/v1/health")
""",
        encoding="utf-8",
    )

    decomposed = DecomposedGoal(
        original_query="Scaffold new billing endpoints",
        intent=GoalIntent.NEW_FEATURE_SCAFFOLD,
        is_scaffold=True,
    )
    score = SufficiencyScore(
        target_file_score=0.9,
        anchor_code_score=0.9,
        callers_score=0.8,
        config_score=0.8,
        total_score=0.85,
        mounting_point="router.py",
    )
    recon = ReconReport(
        query="Scaffold new billing endpoints",
        decomposed=decomposed,
        final_score=score,
    )

    payload = ReadyToCodeSynthesizer.synthesize(
        query="Scaffold new billing endpoints",
        examined_files=["router.py"],
        declarations=[],
        recon_report=recon,
        workspace_root=tmp_path,
    )

    assert payload is not None
    assert len(payload.targets) >= 1
    target = payload.targets[0]
    assert target.role == "mounting_point"
    assert target.file_path == "router.py"
    assert "Mount new scaffold" in target.replacement_content
    assert "```diff" in target.diff_preview


def test_ready_to_code_blast_radius(tmp_path: Path):
    decl = DeclarationUnit(
        name="AuthService",
        kind="class",
        file_path="src/auth.py",
        start_line=1,
        end_line=10,
        signature="class AuthService:",
    )

    rel_report = RelationshipReport(
        links=[
            RelationshipLink(
                source_file="src/api.py",
                caller_unit="login_endpoint",
                target_symbol="AuthService",
                target_file="src/auth.py",
            ),
            RelationshipLink(
                source_file="src/worker.py",
                caller_unit="verify_job",
                target_symbol="AuthService",
                target_file="src/auth.py",
            ),
        ],
        donor_files=["src/db.py"],
    )

    payload = ReadyToCodeSynthesizer.synthesize(
        query="Update AuthService token generation",
        examined_files=["src/auth.py"],
        declarations=[decl],
        relationship_report=rel_report,
        workspace_root=tmp_path,
    )

    assert payload is not None
    assert len(payload.blast_radius) >= 2
    assert any("login_endpoint (src/api.py)" in b for b in payload.blast_radius)
    assert any("verify_job (src/worker.py)" in b for b in payload.blast_radius)


def test_ready_to_code_zero_llm_deterministic(tmp_path: Path):
    decl = DeclarationUnit(
        name="fast_calc",
        kind="function",
        file_path="calc.py",
        start_line=1,
        end_line=3,
        signature="def fast_calc(x):",
    )
    (tmp_path / "calc.py").write_text(
        "def fast_calc(x):\n    return x + 1\n", encoding="utf-8"
    )

    start_time = time.perf_counter()
    payload = ReadyToCodeSynthesizer.synthesize(
        query="Optimize fast_calc addition",
        examined_files=["calc.py"],
        declarations=[decl],
        workspace_root=tmp_path,
    )
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    assert payload is not None
    # Must be sub-50ms deterministic execution
    assert elapsed_ms < 50.0


def test_investigator_explore_attaches_ready_to_code(tmp_path: Path):
    # Set up a small workspace
    p = tmp_path / "module.py"
    p.write_text("def solve_problem():\n    return 42\n", encoding="utf-8")

    investigator = Investigator()
    try:
        # Code modification intent attaches ready_to_code
        res = investigator.explore(
            query="Fix solve_problem return value",
            workspace_path=str(tmp_path),
            max_steps=2,
        )
        assert res.ready_to_code is not None
        assert isinstance(res.ready_to_code, ReadyToCodePayload)
        assert len(res.ready_to_code.targets) >= 1
        assert any("module.py" in t.file_path for t in res.ready_to_code.targets)

        # Survey/exploration intent does NOT attach ready_to_code (Zero Fake Diffs)
        survey_res = investigator.explore(
            query="explain solve_problem structure",
            workspace_path=str(tmp_path),
            max_steps=2,
        )
        assert survey_res.ready_to_code is None
    finally:
        set_workspace_root(None)
