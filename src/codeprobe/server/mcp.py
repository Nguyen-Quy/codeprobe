from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from ..core.learning import FeedbackLearner
from ..core.router import LayaDecisionRouter
from ..executor import Investigator
from ..inventory import scan_inventory
from ..schemas import DecisionRequest, InvestigationFeedback, TaskCategory

logger = logging.getLogger(__name__)


def create_mcp_server(name: str = "codeprobe") -> MCPServer:
    """
    Factory function creating and configuring the codeprobe FastMCP/MCPServer instance.
    """
    server = MCPServer(name)
    router = LayaDecisionRouter()
    investigator = Investigator()

    @server.tool()
    def codeprobe_investigate(
        query: str,
        workspace_path: str | None = None,
        target_files: list[str] | None = None,
        max_steps: int = 5,
        mode: str = "auto",
    ) -> dict[str, Any]:
        """
        Autonomous 1-shot codebase investigation & fact-finding engine.
        MUST be called FIRST before performing manual grep, find, or multi-file reading loops.
        Recursively searches the workspace, inspects .planning and source files, analyzes git diff/logs,
        and returns synthesized findings with citations in a single call.

        Args:
            query: The question, symbol, phase, or topic to investigate.
            workspace_path: The absolute path of the target project workspace (e.g. /path/to/project).
            target_files: Optional candidate file paths to prioritize.
            max_steps: Maximum recursive investigation steps (1-15, default 5).
            mode: Investigation mode override ('auto', 'code', 'compare', 'survey').
        """
        result = investigator.explore(
            query=query,
            target_files=target_files,
            workspace_path=workspace_path,
            max_steps=max(1, min(max_steps, 15)),
            synthesize_summary=True,
            mode=mode,
        )
        return result.model_dump()

    @server.tool()
    def codeprobe_explore(
        query: str,
        workspace_path: str | None = None,
        target_files: list[str] | None = None,
        max_steps: int = 5,
        mode: str = "auto",
    ) -> dict[str, Any]:
        """
        Fast 1-shot repository, symbol, and documentation discovery engine.
        Alias for codeprobe_investigate. Call this before manual exploration.

        Args:
            query: Search query, symbol, or concept.
            workspace_path: The absolute path of the target project workspace.
            target_files: Optional candidate file paths to prioritize.
            max_steps: Maximum exploration steps (1-15, default 5).
            mode: Investigation mode override ('auto', 'code', 'compare', 'survey').
        """
        result = investigator.explore(
            query=query,
            target_files=target_files,
            workspace_path=workspace_path,
            max_steps=max(1, min(max_steps, 15)),
            synthesize_summary=True,
            mode=mode,
        )
        return result.model_dump()

    @server.tool()
    def codeprobe_files(
        workspace_path: str | None = None,
        root_dir: str = ".",
        exclude: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Pre-flight workspace inventory and byte volume breakdown.
        Runs completely offline in milliseconds without consuming LLM tokens.
        Reports total file count, total byte volume, top-level directory distribution,
        and primary programming languages.

        Args:
            workspace_path: Absolute path to the workspace root.
            root_dir: Sub-directory to inventory (defaults to workspace root).
            exclude: Optional list of glob patterns to exclude from inventory.
        """
        base_dir = Path(workspace_path or Path.cwd()).resolve()
        target = (
            (base_dir / root_dir).resolve()
            if root_dir and root_dir != "."
            else base_dir
        )
        inv = scan_inventory(target, exclude_patterns=exclude or [])
        return inv.to_dict()

    @server.tool()
    def codeprobe_decide(
        user_goal: str,
        workspace_path: str | None = None,
        task_category: str | None = None,
        collected_evidence: list[str] | None = None,
        known_files: list[str] | None = None,
        modified_files: list[str] | None = None,
        last_error: str | None = None,
        active_file: str | None = None,
        budget_remaining_steps: int = 5,
        current_step: int = 0,
        auto_investigate: bool = True,
    ) -> dict[str, Any]:
        """
        Pre-flight decision router and guardrail enforcer.
        Evaluates current agent state and returns recommended actions, strictly prohibited steps,
        evidence sufficiency, and optimal model tier.

        Args:
            user_goal: Goal or task description.
            workspace_path: Absolute path to the active project workspace root.
            task_category: Optional category (e.g. investigation, debugging, refactoring, code_edit).
        """
        category_enum = None
        if task_category:
            try:
                category_enum = TaskCategory(task_category.lower())
            except ValueError:
                category_enum = None

        evidence_list = collected_evidence or []
        files_list = known_files or []

        # If step 0 and no evidence gathered, auto-investigate to provide 1-shot answer
        if auto_investigate and not evidence_list and not last_error:
            ws = workspace_path or (Path(active_file).parent if active_file else None)
            inv_res = investigator.explore(
                query=user_goal, target_files=files_list, workspace_path=ws, max_steps=3
            )
            evidence_list = inv_res.evidence_snippets
            files_list = inv_res.examined_files

        request = DecisionRequest(
            user_goal=user_goal,
            task_category=category_enum,
            current_step=current_step,
            collected_evidence=evidence_list,
            known_files=files_list,
            modified_files=modified_files or [],
            last_error=last_error,
            active_file=active_file,
            budget_remaining_steps=budget_remaining_steps,
        )

        response = router.route(request)
        dump = response.model_dump()
        if auto_investigate and "inv_res" in locals():
            dump["summary"] = inv_res.summary
            dump["examined_files"] = inv_res.examined_files
            dump["reasoning"] = f"{inv_res.summary}\n\n{response.reasoning}"
        return dump

    @server.tool()
    def codeprobe_recommend_strategy(
        user_goal: str,
        task_category: str | None = None,
        last_error: str | None = None,
    ) -> dict[str, Any]:
        """
        Lightweight early triage tool: recommends high-level execution strategy
        and optimal model routing tier (fast vs standard vs reasoning).
        """
        category_enum = None
        if task_category:
            try:
                category_enum = TaskCategory(task_category.lower())
            except ValueError:
                category_enum = None

        request = DecisionRequest(
            user_goal=user_goal,
            task_category=category_enum,
            last_error=last_error,
        )

        response = router.route(request)
        return {
            "strategy": response.strategy,
            "suggested_model_tier": response.suggested_model_tier.value,
            "confidence": response.confidence,
            "reasoning": response.reasoning,
        }

    @server.tool()
    def codeprobe_evaluate_evidence(
        user_goal: str,
        collected_evidence: list[str] | None = None,
        budget_remaining_steps: int = 5,
        known_files: list[str] | None = None,
        last_error: str | None = None,
    ) -> dict[str, Any]:
        """
        Evidence sufficiency validator: evaluates whether gathered context is sufficient
        to formulate an answer or whether further search/inspection is required.
        """
        request = DecisionRequest(
            user_goal=user_goal,
            collected_evidence=collected_evidence or [],
            known_files=known_files or [],
            last_error=last_error,
            budget_remaining_steps=budget_remaining_steps,
        )

        response = router.route(request)
        next_action = (
            response.recommended_actions[0].action.value
            if response.recommended_actions
            else None
        )
        return {
            "is_sufficient": response.is_sufficient,
            "strategy": response.strategy,
            "confidence": response.confidence,
            "recommended_next_action": next_action,
            "reasoning": response.reasoning,
        }

    @server.tool()
    def codeprobe_explain_decision(
        user_goal: str,
        task_category: str | None = None,
        collected_evidence: list[str] | None = None,
        known_files: list[str] | None = None,
        last_error: str | None = None,
    ) -> dict[str, Any]:
        """
        Detailed breakdown explaining why specific actions or model tiers were selected,
        including raw probability scores and active heuristic triggers.
        """
        category_enum = None
        if task_category:
            try:
                category_enum = TaskCategory(task_category.lower())
            except ValueError:
                category_enum = None

        request = DecisionRequest(
            user_goal=user_goal,
            task_category=category_enum,
            collected_evidence=collected_evidence or [],
            known_files=known_files or [],
            last_error=last_error,
        )

        response = router.route(request)
        return {
            "strategy": response.strategy,
            "suggested_model_tier": response.suggested_model_tier.value,
            "raw_probabilities": response.raw_probabilities,
            "prohibited_actions": response.prohibited_actions,
            "reasoning": response.reasoning,
        }

    @server.tool()
    def codeprobe_feedback(
        investigation_id: str,
        score: int,
        feedback_text: str | None = None,
        helpful_files: list[str] | None = None,
        unhelpful_files: list[str] | None = None,
        workspace_path: str | None = None,
    ) -> dict[str, Any]:
        """
        Feedback & Reinforcement Learning loop for CodeProbe.
        Submits evaluation from an agent or user to calibrate weight matrices and self-train CodeProbe.

        Args:
            investigation_id: The ID of the investigation to evaluate (returned in investigation_id field).
            score: Quality rating from 1 (poor/irrelevant) to 5 (accurate, complete, highly helpful).
            feedback_text: Optional text describing what was accurate or what was missed.
            helpful_files: Optional list of files that were essential to solving the task.
            unhelpful_files: Optional list of files that were irrelevant noise.
            workspace_path: The project workspace directory.
        """
        fb = InvestigationFeedback(
            investigation_id=investigation_id,
            score=max(1, min(score, 5)),
            feedback_text=feedback_text,
            helpful_files=helpful_files,
            unhelpful_files=unhelpful_files,
            workspace_path=workspace_path,
        )
        resp = FeedbackLearner.process_feedback(fb)
        return resp.model_dump()

    return server


def run_mcp_server(
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """
    Run the codeprobe MCP server on the specified transport.
    """
    server = create_mcp_server()
    if transport == "sse":
        logger.info(
            "Starting codeprobe MCP server with SSE transport on %s:%d", host, port
        )
        server.run(transport="sse", host=host, port=port)
    else:
        logger.info("Starting codeprobe MCP server with stdio transport")
        server.run(transport="stdio")
