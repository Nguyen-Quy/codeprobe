from codeprobe.core.recon import classify_investigation_mode
from codeprobe.schemas import (
    ComparisonMatrixPayload,
    ComparisonTarget,
    InvestigationMode,
    InvestigationResult,
)


def test_investigation_mode_enum():
    assert InvestigationMode.AUTO == "auto"
    assert InvestigationMode.CODE_MODIFICATION == "code"
    assert InvestigationMode.AUDIT_COMPARE == "compare"
    assert InvestigationMode.SURVEY_EXPLORATION == "survey"


def test_comparison_schemas_structure():
    target = ComparisonTarget(
        aspect="deploy",
        source_component="scripts/deploy_k8s.sh",
        target_component="tools/erp-cli/src/deploy.rs",
        parity_status="PARTIAL",
        missing_in_target=["image_build", "containerd_import"],
        details="Missing docker build and ctr import steps",
    )
    assert target.aspect == "deploy"
    assert "image_build" in target.missing_in_target

    payload = ComparisonMatrixPayload(
        title="Bash vs Rust Parity",
        subsystems_detected=["bash_scripts", "rust_crate"],
        component_pairs=[target],
        architectural_gaps=["Lacks dynamic tenant lifecycle"],
    )
    assert len(payload.component_pairs) == 1
    assert payload.subsystems_detected == ["bash_scripts", "rust_crate"]

    result = InvestigationResult(
        user_goal="so sánh bash và rust",
        strategy="READY_TO_SYNTHESIZE",
        summary="Comparison completed",
        mode=InvestigationMode.AUDIT_COMPARE,
        comparison_matrix=payload,
    )
    assert result.mode == InvestigationMode.AUDIT_COMPARE
    assert result.comparison_matrix is not None
    assert result.ready_to_code is None


def test_classify_investigation_mode_auto():
    # Compare queries
    assert (
        classify_investigation_mode("so sánh script bash deploy và crate erp-cli rust")
        == InvestigationMode.AUDIT_COMPARE
    )
    assert (
        classify_investigation_mode("compare bash deploy and rust implementation")
        == InvestigationMode.AUDIT_COMPARE
    )
    assert (
        classify_investigation_mode("coi erp-cli có thiếu chức năng nào có ở bash script ko")
        == InvestigationMode.AUDIT_COMPARE
    )
    assert (
        classify_investigation_mode("audit feature parity between services")
        == InvestigationMode.AUDIT_COMPARE
    )

    # Code modification queries
    assert (
        classify_investigation_mode("sửa lỗi cú pháp trong synthesizer.py")
        == InvestigationMode.CODE_MODIFICATION
    )
    assert (
        classify_investigation_mode("tối ưu các script backup và DR")
        == InvestigationMode.CODE_MODIFICATION
    )
    assert (
        classify_investigation_mode("refactor error handling in executor.py")
        == InvestigationMode.CODE_MODIFICATION
    )
    assert (
        classify_investigation_mode("implement new endpoint for metrics")
        == InvestigationMode.CODE_MODIFICATION
    )

    # Pure survey / exploration queries
    assert (
        classify_investigation_mode("tìm các file liên quan đến auth")
        == InvestigationMode.SURVEY_EXPLORATION
    )
    assert (
        classify_investigation_mode("where is the entrypoint defined?")
        == InvestigationMode.SURVEY_EXPLORATION
    )


def test_classify_investigation_mode_explicit_override():
    # Query says "so sánh" but explicit mode is "code"
    assert (
        classify_investigation_mode("so sánh hai file", explicit_mode="code")
        == InvestigationMode.CODE_MODIFICATION
    )
    # Query says "fix" but explicit mode is "compare"
    assert (
        classify_investigation_mode("fix bug in auth", explicit_mode="compare")
        == InvestigationMode.AUDIT_COMPARE
    )
    # Using enum directly
    assert (
        classify_investigation_mode(
            "explain logic", explicit_mode=InvestigationMode.CODE_MODIFICATION
        )
        == InvestigationMode.CODE_MODIFICATION
    )
