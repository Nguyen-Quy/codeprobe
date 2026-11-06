import json

import pytest

from codeprobe.server.mcp import create_mcp_server


@pytest.mark.anyio
async def test_mcp_server_lists_all_tools():
    server = create_mcp_server()
    tools = await server.list_tools()
    tool_names = [t.name for t in tools]
    assert "codeprobe_decide" in tool_names
    assert "codeprobe_recommend_strategy" in tool_names
    assert "codeprobe_evaluate_evidence" in tool_names
    assert "codeprobe_explain_decision" in tool_names
    assert "codeprobe_files" in tool_names


@pytest.mark.anyio
async def test_mcp_codeprobe_decide_tool():
    server = create_mcp_server()
    res = await server.call_tool(
        "codeprobe_decide",
        {
            "user_goal": "Locate webhook handler",
            "task_category": "investigation",
            "collected_evidence": [],
            "known_files": [],
        },
    )
    assert not res.is_error
    data = json.loads(res.content[0].text)
    assert "strategy" in data
    assert "confidence" in data
    assert "recommended_actions" in data
    assert "suggested_model_tier" in data


@pytest.mark.anyio
async def test_mcp_codeprobe_recommend_strategy_tool():
    server = create_mcp_server()
    res = await server.call_tool(
        "codeprobe_recommend_strategy",
        {
            "user_goal": "Refactor auth middleware",
            "task_category": "refactoring",
        },
    )
    assert not res.is_error
    data = json.loads(res.content[0].text)
    assert data["strategy"] in (
        "MAP_BLAST_RADIUS",
        "EXPAND_SEARCH",
        "GENERAL_INVESTIGATION",
    )
    assert data["suggested_model_tier"] == "reasoning"
    assert "confidence" in data


@pytest.mark.anyio
async def test_mcp_codeprobe_evaluate_evidence_tool():
    server = create_mcp_server()
    res = await server.call_tool(
        "codeprobe_evaluate_evidence",
        {
            "user_goal": "Find auth token",
            "collected_evidence": [
                "=== SEARCH ===\nauth.py:12:def get_token(): ...",
                "=== FILE ===\nauth.py content",
                "=== TESTS ===\nPassed",
            ],
            "known_files": ["src/auth.py"],
            "budget_remaining_steps": 4,
        },
    )
    assert not res.is_error
    data = json.loads(res.content[0].text)
    assert data["is_sufficient"] is True
    assert data["strategy"] == "READY_TO_SYNTHESIZE"


@pytest.mark.anyio
async def test_mcp_codeprobe_explain_decision_tool():
    server = create_mcp_server()
    res = await server.call_tool(
        "codeprobe_explain_decision",
        {
            "user_goal": "Find database configuration",
            "task_category": "investigation",
        },
    )
    assert not res.is_error
    data = json.loads(res.content[0].text)
    assert "raw_probabilities" in data
    assert "prohibited_actions" in data
    assert "strategy" in data


@pytest.mark.anyio
async def test_mcp_codeprobe_files_tool():
    server = create_mcp_server()
    res = await server.call_tool(
        "codeprobe_files",
        {
            "root_dir": ".",
        },
    )
    assert not res.is_error
    data = json.loads(res.content[0].text)
    assert "total_files" in data
    assert "breakdown_by_dir" in data
    assert data["total_files"] > 0
