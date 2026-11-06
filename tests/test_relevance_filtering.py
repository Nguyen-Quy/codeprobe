from __future__ import annotations

from pathlib import Path

from codeprobe.core.declarations import (
    GENERIC_ENV_BLACKLIST,
    NOISE_FUNCTION_BLACKLIST,
    DeclarationParser,
    DeclarationUnit,
)
from codeprobe.core.recon import (
    RelevanceScorer,
    classify_investigation_mode,
)
from codeprobe.core.synthesizer import (
    ComparisonMatrixSynthesizer,
    ReadyToCodeSynthesizer,
)
from codeprobe.executor import Investigator
from codeprobe.schemas import (
    ComparisonMatrixPayload,
    InvestigationMode,
)
from codeprobe.tools import set_workspace_root


def test_investigation_mode_classification():
    # 1. Compare / Audit intent
    compare_queries = [
        "so sánh script bash deploy và backup, DR ở repo vnrex_crm và crate erp-cli viết bằng rust",
        "compare docker-compose with kubernetes manifests",
        "audit feature parity between bash scripts and cli",
        "erp-cli có thiếu chức năng nào so với bash script không",
        "gap analysis on disaster recovery",
    ]
    for q in compare_queries:
        assert (
            classify_investigation_mode(q) == InvestigationMode.AUDIT_COMPARE
        ), f"Failed for {q}"

    # 2. Code modification intent
    code_queries = [
        "fix authentication token expiration error",
        "refactor payment gateway processor",
        "tối ưu script backup tenant",
        "thêm code xử lý replication lag",
        "patch CVE vulnerability in dependencies",
        "Add REDIS_BROKER_URL support across worker and infra",
    ]
    for q in code_queries:
        assert (
            classify_investigation_mode(q) == InvestigationMode.CODE_MODIFICATION
        ), f"Failed for {q}"

    # 3. Survey / Exploration intent
    survey_queries = [
        "where is the user authentication defined?",
        "explain the database backup architecture",
        "trace request flow from gateway to service",
        "tìm symbol ConnectionPool",
    ]
    for q in survey_queries:
        assert (
            classify_investigation_mode(q) == InvestigationMode.SURVEY_EXPLORATION
        ), f"Failed for {q}"

    # 4. Explicit mode override
    assert (
        classify_investigation_mode("any random query", explicit_mode="compare")
        == InvestigationMode.AUDIT_COMPARE
    )
    assert (
        classify_investigation_mode("any random query", explicit_mode="code")
        == InvestigationMode.CODE_MODIFICATION
    )
    assert (
        classify_investigation_mode("any random query", explicit_mode="survey")
        == InvestigationMode.SURVEY_EXPLORATION
    )


def test_noise_blacklist_filtering():
    # Check that standard boilerplate functions exist in blacklist
    assert "usage" in NOISE_FUNCTION_BLACKLIST
    assert "help" in NOISE_FUNCTION_BLACKLIST
    assert "check_kubectl" in NOISE_FUNCTION_BLACKLIST
    assert "check_env" in NOISE_FUNCTION_BLACKLIST
    assert "print_error" in NOISE_FUNCTION_BLACKLIST

    # Check generic env blacklist
    assert "$1" in GENERIC_ENV_BLACKLIST
    assert "TARGET" in GENERIC_ENV_BLACKLIST
    assert "KUBECONFIG" in GENERIC_ENV_BLACKLIST
    assert "PATH" in GENERIC_ENV_BLACKLIST
    assert "SCRIPT_DIR" in GENERIC_ENV_BLACKLIST

    # Parsing bash script should filter noise functions
    bash_code = """#!/usr/bin/env bash
usage() {
    echo "Usage: $0"
}

check_kubectl() {
    command -v kubectl || exit 1
}

deploy_production() {
    kubectl apply -f k8s/deploy.yaml
}

backup_database() {
    restic backup /var/data
}
"""
    units = DeclarationParser.parse(bash_code, file_path="scripts/deploy.sh")
    unit_names = [u.name for u in units]

    assert "usage" not in unit_names
    assert "check_kubectl" not in unit_names
    assert "deploy_production" in unit_names
    assert "backup_database" in unit_names


def test_relevance_scorer_ranking():
    decls = [
        DeclarationUnit(
            name="execute_dr_failover",
            kind="function",
            file_path="scripts/dr.sh",
            signature="execute_dr_failover()",
            docstring="Performs disaster recovery failover to secondary cloud",
            start_line=10,
            end_line=25,
        ),
        DeclarationUnit(
            name="backup_tenant_databases",
            kind="function",
            file_path="scripts/backup.sh",
            signature="backup_tenant_databases()",
            docstring="Backs up all active tenant Postgres databases",
            start_line=1,
            end_line=20,
        ),
        DeclarationUnit(
            name="random_unrelated_helper",
            kind="function",
            file_path="utils/misc.py",
            signature="def random_unrelated_helper():",
            start_line=1,
            end_line=5,
        ),
    ]

    filtered = RelevanceScorer.filter_and_rank_declarations(
        decls,
        query="Disaster recovery failover script and backup",
        threshold=0.40,
        top_k=5,
    )

    names = [d.name for d in filtered]
    assert "execute_dr_failover" in names
    assert "backup_tenant_databases" in names
    assert "random_unrelated_helper" not in names
    # DR failover should be ranked first
    assert names[0] == "execute_dr_failover"


def test_zero_fake_diffs_policy(tmp_path: Path):
    src = tmp_path / "app.py"
    src.write_text("class CoreApp:\n    def run(self):\n        return True\n")

    decl = DeclarationUnit(
        name="CoreApp",
        kind="class",
        file_path="app.py",
        start_line=1,
        end_line=3,
        signature="class CoreApp:",
        body_snippet="class CoreApp:\n    def run(self):\n        return True",
    )

    # 1. In SURVEY mode: ready_to_code MUST be None
    payload_survey = ReadyToCodeSynthesizer.synthesize(
        query="explain CoreApp architecture",
        examined_files=["app.py"],
        declarations=[decl],
        workspace_root=tmp_path,
        mode=InvestigationMode.SURVEY_EXPLORATION,
    )
    assert payload_survey is None

    # 2. In AUDIT_COMPARE mode: ready_to_code MUST be None
    payload_compare = ReadyToCodeSynthesizer.synthesize(
        query="compare CoreApp with legacy",
        examined_files=["app.py"],
        declarations=[decl],
        workspace_root=tmp_path,
        mode=InvestigationMode.AUDIT_COMPARE,
    )
    assert payload_compare is None

    # 3. In CODE_MODIFICATION mode: No fake comment injections
    payload_code = ReadyToCodeSynthesizer.synthesize(
        query="refactor CoreApp run method",
        examined_files=["app.py"],
        declarations=[decl],
        workspace_root=tmp_path,
        mode=InvestigationMode.CODE_MODIFICATION,
    )
    assert payload_code is not None
    target = payload_code.targets[0]
    assert "# Ready-to-Code:" not in target.replacement_content
    assert target.replacement_content == target.current_code
    assert target.diff_preview == ""


def test_comparison_matrix_generation(tmp_path: Path):
    # Set up mock repository with Bash scripts vs Rust crate
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True)
    deploy_sh = scripts_dir / "deploy_k8s.sh"
    deploy_sh.write_text("""#!/bin/bash
image_build() { docker build -t app:latest .; }
containerd_import() { ctr image import app.tar; }
migration_job_wait() { kubectl wait --for=condition=complete job/migrate; }
""")

    backup_sh = scripts_dir / "backup_tenant.sh"
    backup_sh.write_text("""#!/bin/bash
full_retention_policy() { restic forget --keep-daily 7 --prune; }
dead_mans_snitch_heartbeat() { curl -fsS https://nosnch.in/xxxx; }
telegram_alert() { curl -s -X POST https://api.telegram.org/bot/sendMessage; }
""")

    tools_dir = tmp_path / "tools" / "erp-cli" / "src"
    tools_dir.mkdir(parents=True)
    deploy_rs = tools_dir / "deploy.rs"
    deploy_rs.write_text("""
pub fn execute_deploy() {
    println!("Deploying via helm");
}
""")

    backup_rs = tools_dir / "backup.rs"
    backup_rs.write_text("""
pub fn execute_backup() {
    println!("Running backup");
}
""")

    examined = [
        "scripts/deploy_k8s.sh",
        "scripts/backup_tenant.sh",
        "tools/erp-cli/src/deploy.rs",
        "tools/erp-cli/src/backup.rs",
    ]

    decls = [
        DeclarationUnit(name="image_build", kind="function", signature="image_build()", file_path="scripts/deploy_k8s.sh", start_line=2, end_line=2),
        DeclarationUnit(name="containerd_import", kind="function", signature="containerd_import()", file_path="scripts/deploy_k8s.sh", start_line=3, end_line=3),
        DeclarationUnit(name="migration_job_wait", kind="function", signature="migration_job_wait()", file_path="scripts/deploy_k8s.sh", start_line=4, end_line=4),
        DeclarationUnit(name="full_retention_policy", kind="function", signature="full_retention_policy()", file_path="scripts/backup_tenant.sh", start_line=2, end_line=2),
        DeclarationUnit(name="dead_mans_snitch_heartbeat", kind="function", signature="dead_mans_snitch_heartbeat()", file_path="scripts/backup_tenant.sh", start_line=3, end_line=3),
        DeclarationUnit(name="telegram_alert", kind="function", signature="telegram_alert()", file_path="scripts/backup_tenant.sh", start_line=4, end_line=4),
        DeclarationUnit(name="execute_deploy", kind="function", signature="pub fn execute_deploy()", file_path="tools/erp-cli/src/deploy.rs", start_line=2, end_line=4),
        DeclarationUnit(name="execute_backup", kind="function", signature="pub fn execute_backup()", file_path="tools/erp-cli/src/backup.rs", start_line=2, end_line=4),
    ]

    payload = ComparisonMatrixSynthesizer.synthesize(
        query="compare bash deploy and backup scripts against erp-cli rust crate",
        examined_files=examined,
        declarations=decls,
        workspace_root=tmp_path,
    )

    assert isinstance(payload, ComparisonMatrixPayload)
    assert "bash_scripts" in payload.subsystems_detected
    assert "rust_crate" in payload.subsystems_detected
    assert len(payload.component_pairs) >= 2

    deploy_pair = next(p for p in payload.component_pairs if p.aspect == "deploy")
    assert deploy_pair.source_component == "scripts/deploy_k8s.sh"
    assert deploy_pair.target_component == "tools/erp-cli/src/deploy.rs"
    assert deploy_pair.parity_status in ("PARTIAL", "MISSING_IN_TARGET")
    assert any("image_build" in m or "containerd_import" in m for m in deploy_pair.missing_in_target)

    backup_pair = next(p for p in payload.component_pairs if p.aspect == "backup")
    assert backup_pair.parity_status in ("PARTIAL", "MISSING_IN_TARGET")
    assert any("telegram_alert" in m or "dead_mans_snitch" in m or "full_retention" in m for m in backup_pair.missing_in_target)

    assert len(payload.architectural_gaps) >= 1


def test_investigator_e2e_comparison_vs_code_modes(tmp_path: Path):
    # Set up files
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "deploy.sh").write_text("#!/bin/bash\nimage_build() { docker build .; }\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text("fn main() {}\n")

    investigator = Investigator()
    try:
        # Comparison query
        res_compare = investigator.explore(
            query="so sánh scripts deploy và main.rs",
            workspace_path=str(tmp_path),
            max_steps=2,
        )
        assert res_compare.mode == InvestigationMode.AUDIT_COMPARE
        assert res_compare.comparison_matrix is not None
        assert res_compare.ready_to_code is None
        assert "Comparison Matrix" in res_compare.summary

        # Code modification query
        res_code = investigator.explore(
            query="refactor main.rs to print hello",
            workspace_path=str(tmp_path),
            max_steps=2,
        )
        assert res_code.mode == InvestigationMode.CODE_MODIFICATION
        assert res_code.comparison_matrix is None
        assert res_code.ready_to_code is not None
    finally:
        set_workspace_root(None)
