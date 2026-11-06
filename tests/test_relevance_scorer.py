from codeprobe.core.declarations import (
    GENERIC_ENV_BLACKLIST,
    NOISE_FUNCTION_BLACKLIST,
    DeclarationUnit,
)
from codeprobe.core.infra.shell import ShellEnvResolver
from codeprobe.core.recon import RelevanceScorer


def test_noise_blacklists_defined():
    assert "usage" in NOISE_FUNCTION_BLACKLIST
    assert "check_kubectl" in NOISE_FUNCTION_BLACKLIST
    assert "1" in GENERIC_ENV_BLACKLIST
    assert "KUBECONFIG" in GENERIC_ENV_BLACKLIST
    assert "PATH" in GENERIC_ENV_BLACKLIST


def test_shell_script_pruning():
    script_content = """#!/bin/bash
export KUBECONFIG="/etc/rancher/k3s/k3s.yaml"
export DATABASE_URL="postgres://user:pass@localhost/db"
TARGET="${1:-dev}"
ENVIRONMENT="${2:-dev}"

usage() {
    echo "Usage: deploy"
    exit 1
}

check_kubectl() {
    command -v kubectl || exit 1
}

execute_deploy() {
    echo "Deploying to $TARGET"
}
"""
    units = ShellEnvResolver.parse_shell_script(script_content, "deploy.sh")
    names = [u.name for u in units]

    # Verify blacklisted noise is pruned
    assert "KUBECONFIG" not in names
    assert "TARGET" not in names
    assert "ENVIRONMENT" not in names
    assert "usage" not in names
    assert "check_kubectl" not in names

    # Verify valuable business logic remains
    assert "DATABASE_URL" in names
    assert "execute_deploy" in names


def test_relevance_scorer_ranking():
    d1 = DeclarationUnit(
        name="usage",
        kind="function",
        file_path="scripts/deploy.sh",
        start_line=1,
        end_line=5,
        signature="function usage()",
        body_snippet="echo usage",
    )
    d2 = DeclarationUnit(
        name="execute_deploy",
        kind="function",
        file_path="tools/erp-cli/src/deploy.rs",
        start_line=10,
        end_line=30,
        signature="pub fn execute_deploy(target: &str) -> Result<()>",
        docstring="Deploys application workloads to Kubernetes cluster",
        body_snippet="apply manifests",
    )
    d3 = DeclarationUnit(
        name="ApartmentTypeAttributes",
        kind="class",
        file_path="apps/projects/unit_validation.py",
        start_line=100,
        end_line=120,
        signature="class ApartmentTypeAttributes(BaseModel):",
        body_snippet="model config",
    )

    query = "so sánh script bash deploy và crate erp-cli rust"

    # d1 is blacklisted -> score 0.0
    assert RelevanceScorer.score_declaration(d1, query) == 0.0

    # d2 contains deploy & matches query -> high score
    s2 = RelevanceScorer.score_declaration(d2, query)
    assert s2 >= 0.60

    # d3 is unrelated CRM model -> low score
    s3 = RelevanceScorer.score_declaration(d3, query)
    assert s3 < 0.40

    # Filter and rank should only include d2
    filtered = RelevanceScorer.filter_and_rank_declarations(
        [d1, d2, d3], query, threshold=0.40
    )
    assert len(filtered) == 1
    assert filtered[0].name == "execute_deploy"
