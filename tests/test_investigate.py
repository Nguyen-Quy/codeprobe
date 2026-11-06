from __future__ import annotations

from unittest.mock import patch

from codeprobe.executor import Investigator
from codeprobe.server.mcp import create_mcp_server
from codeprobe.tools import set_workspace_root


@patch("codeprobe.executor.solve", return_value="Mocked LLM investigation summary")
def test_investigator_explore_basic(mock_solve):
    investigator = Investigator()
    result = investigator.explore(query="LayaDecisionRouter in router.py", max_steps=2)

    assert result.user_goal == "LayaDecisionRouter in router.py"
    assert len(result.examined_files) > 0
    assert any("router" in f for f in result.examined_files)
    assert result.confidence > 0.0
    assert result.summary != ""


def test_mcp_codeprobe_investigate_tool():
    server = create_mcp_server()
    assert (
        hasattr(server, "list_tools")
        or hasattr(server, "_tool_manager")
        or hasattr(server, "call_tool")
    )


@patch("codeprobe.executor.solve", return_value="Mocked schemas synthesis")
def test_investigate_mcp_tool_invocation(mock_solve):
    investigator = Investigator()
    res = investigator.explore(query="DecisionRequest schemas", max_steps=2)
    assert "schemas" in str(res.examined_files)
    assert res.is_sufficient is True


def test_investigate_dynamic_workspace(tmp_path):
    sub_project = tmp_path / "my_other_project"
    sub_project.mkdir()
    plan_dir = sub_project / ".planning" / "phases" / "12.1-crm"
    plan_dir.mkdir(parents=True)
    plan_file = plan_dir / "12.1-CONTEXT.md"
    plan_file.write_text(
        "# Phase 12.1 CRM Implementation Status: Complete\nAll endpoints active."
    )

    investigator = Investigator()
    try:
        res = investigator.explore(
            query="phase 12.1 status summary",
            workspace_path=str(sub_project),
            max_steps=2,
        )
        assert any("12.1-CONTEXT.md" in f for f in res.examined_files)
        assert "Phase 12.1 CRM Implementation" in "\n".join(res.evidence_snippets)
    finally:
        set_workspace_root(None)


def test_deterministic_fallback_synthesis():
    investigator = Investigator()
    evidence = (
        "=== FILE: .planning/phases/12.1-hrm/12.1-01-PLAN.md ===\n"
        "---\nphase: 12.1-hrm\nwave: 1\nstatus: completed\n---\n<objective>Build Wave 1</objective>\n\n"
        "=== GIT LOG: 12.1 ===\n"
        "a1b2c3d feat(hrm): complete wave 1 attendance\n"
    )
    summary = investigator._deterministic_fallback_synthesis(
        "phase 12.1 status", evidence, [".planning/phases/12.1-hrm/12.1-01-PLAN.md"]
    )
    assert "Phase Execution & Plans Status" in summary
    assert "12.1-01-PLAN.md" in summary
    assert "COMPLETED" in summary
    assert "Git Activity" in summary
