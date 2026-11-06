from __future__ import annotations

from pathlib import Path

from codeprobe.core.infra.shell import ShellEnvResolver
from codeprobe.core.infra.yaml_synth import StructuralYamlSynthesizer
from codeprobe.core.recon import (
    ContextSufficiencyEvaluator,
    GoalDecomposer,
    GoalIntent,
)
from codeprobe.core.synthesizer import ReadyToCodeSynthesizer
from codeprobe.schemas import DeclarationUnit, QueryDomain


def test_query_domain_classification():
    # 1. DevOps / Infra queries
    d1 = GoalDecomposer.decompose(
        "find and optimize backup disaster recovery DR scripts"
    )
    assert d1.domain == QueryDomain.INFRA_DEVOPS
    assert d1.intent == GoalIntent.INFRA_CONFIG

    d2 = GoalDecomposer.decompose(
        "check kubernetes cronjob-backup and restic snapshots"
    )
    assert d2.domain == QueryDomain.INFRA_DEVOPS

    # 2. Pure Application logic
    d3 = GoalDecomposer.decompose(
        "how is user session authentication token validated in auth_service?"
    )
    assert d3.domain == QueryDomain.APPLICATION_LOGIC
    assert d3.intent == GoalIntent.CODE_LOGIC

    # 3. Hybrid query (crash in infrastructure deploy)
    d4 = GoalDecomposer.decompose("TypeError: NoneType in docker compose deploy script")
    assert d4.domain == QueryDomain.HYBRID
    assert d4.intent == GoalIntent.ERROR_TRACE


def test_domain_weighted_ranking_penalty():
    decomposed = GoalDecomposer.decompose(
        "optimize disaster recovery postgres backup script"
    )
    assert decomposed.domain == QueryDomain.INFRA_DEVOPS

    # Candidate files containing both infra and unrelated app services
    candidates = [
        "apps/opportunities/tests/test_services_recovery.py",
        "deploy/kubernetes/backup/scripts/backup.sh",
        "apps/opportunities/services/lifecycle.py",
    ]

    # Declarations with non-infra anchor only
    app_decls = [
        DeclarationUnit(
            name="OpportunityRecoveryServicesTestCase",
            kind="class",
            file_path="apps/opportunities/tests/test_services_recovery.py",
            start_line=15,
            end_line=195,
            signature="class OpportunityRecoveryServicesTestCase(BaseOpportunityServicesTestCase):",
        )
    ]

    score = ContextSufficiencyEvaluator.evaluate(
        decomposed=decomposed,
        candidate_files=candidates,
        declarations=app_decls,
        cross_file_links=[],
        discovered_env_vars=set(),
        found_config_files=[],
        threshold=0.80,
    )

    # 1. Target file should automatically prioritize the infra script over CRM test
    assert score.target_file == "deploy/kubernetes/backup/scripts/backup.sh"

    # 2. Because declarations only had non-infra CRM test, anchor code score gets weighted penalty (0.10)
    assert score.anchor_code_score == 0.10
    assert "infra_specific_code_anchor" in score.missing_aspects


def test_shell_script_full_declarations():
    script_content = """#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_NAMESPACE="${1:-vnrex-crm-prod}"
SNAPSHOT_ID="${2:-latest}"
export RESTIC_REPOSITORY="/var/backup"

cleanup() {
    echo "Cleaning staging dir..."
    rm -rf /tmp/backup_stage
}

trap cleanup EXIT

function send_failure_alert() {
    local err="$1"
    echo "ALERT: $err"
}

trap send_failure_alert ERR
"""
    units = ShellEnvResolver.parse_shell_script(script_content, "scripts/backup.sh")

    names = {u.name: u for u in units}
    kinds = {u.name: u.kind for u in units}

    # Verify functions
    assert "cleanup" in names
    assert kinds["cleanup"] == "function"
    assert names["cleanup"].start_line == 8
    assert names["cleanup"].end_line == 11

    assert "send_failure_alert" in names
    assert kinds["send_failure_alert"] == "function"

    # Verify trap handlers
    assert "trap_exit" in names
    assert kinds["trap_exit"] == "handler"
    assert "cleanup" in names["trap_exit"].calls

    assert "trap_err" in names
    assert kinds["trap_err"] == "handler"

    # Verify positional CLI argument assignments
    assert "TARGET_NAMESPACE" in names
    assert kinds["TARGET_NAMESPACE"] == "argument"
    assert "SNAPSHOT_ID" in names
    assert kinds["SNAPSHOT_ID"] == "argument"

    # Verify env var
    assert "RESTIC_REPOSITORY" in names
    assert kinds["RESTIC_REPOSITORY"] == "env_var"


def test_yaml_structural_cronjob_container_anchoring():
    cronjob_yaml = """apiVersion: batch/v1
kind: CronJob
metadata:
  name: cronjob-backup
spec:
  schedule: "*/15 * * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup-worker
              image: restic/restic:latest
              command: ["/bin/sh", "/scripts/backup.sh"]
"""
    res = StructuralYamlSynthesizer.synthesize_k8s_env_target(
        file_path="deploy/kubernetes/backup/cronjob-backup.yaml",
        content=cronjob_yaml,
        env_var_name="RESTIC_PASSWORD",
        secret_name="crm-secrets",
    )
    assert res is not None
    _, _, target_content, replacement_content = res

    # Check that replacement contains valid container env indentation (14-18 spaces)
    assert "- name: backup-worker" in target_content
    assert "env:\n" in replacement_content
    assert "              - name: RESTIC_PASSWORD\n" in replacement_content
    assert "                  name: crm-secrets\n" in replacement_content


def test_yaml_structural_kustomization_anchoring():
    kustomize_yaml = """apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - cronjob-backup.yaml
  - cronjob-prune.yaml
"""
    res = StructuralYamlSynthesizer.synthesize_kustomize_resource_target(
        file_path="deploy/kubernetes/backup/kustomization.yaml",
        content=kustomize_yaml,
        resource_path="scripts/backup.sh",
    )
    assert res is not None
    _start_l, _end_l, target_content, replacement_content = res

    assert "- cronjob-prune.yaml" in target_content
    assert "  - scripts/backup.sh\n" in replacement_content


def test_deep_infra_blast_radius_cascade(tmp_path: Path):
    # Setup mock workspace topology
    backup_sh = tmp_path / "scripts" / "backup.sh"
    backup_sh.parent.mkdir(parents=True)
    backup_sh.write_text("cleanup() { echo 'done'; }\ntrap cleanup EXIT\n")

    kust_yaml = tmp_path / "deploy" / "kustomization.yaml"
    kust_yaml.parent.mkdir(parents=True)
    kust_yaml.write_text(
        "configMapGenerator:\n  - name: backup-scripts\n    files:\n      - ../scripts/backup.sh\n"
    )

    cron_yaml = tmp_path / "deploy" / "cronjob-backup.yaml"
    cron_yaml.write_text(
        "apiVersion: batch/v1\nkind: CronJob\nspec:\n  template:\n    spec:\n      containers:\n        - name: worker\n          command: ['/bin/sh', 'backup.sh']\n"
    )

    examined = [
        "scripts/backup.sh",
        "deploy/kustomization.yaml",
        "deploy/cronjob-backup.yaml",
    ]

    target = DeclarationUnit(
        name="cleanup",
        kind="function",
        file_path="scripts/backup.sh",
        start_line=1,
        end_line=2,
        signature="cleanup()",
    )

    payload = ReadyToCodeSynthesizer.synthesize(
        query="optimize backup.sh disaster recovery script",
        examined_files=examined,
        declarations=[target],
        recon_report=None,
        relationship_report=None,
        workspace_root=tmp_path,
    )

    assert payload is not None
    assert len(payload.targets) > 0

    # Verify cascading blast radius includes kustomize generator and k8s workload
    blast = " ".join(payload.blast_radius)
    assert "kustomize_generator" in blast
    assert "deploy/kustomization.yaml" in blast
    assert "k8s_workload" in blast
    assert "deploy/cronjob-backup.yaml" in blast
