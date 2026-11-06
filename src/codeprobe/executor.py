from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .cache import LocalEvidenceCache
from .config import load_config
from .core.declarations import DeclarationParser, DeclarationUnit
from .core.evidence import EvidenceManager
from .core.learning import FeedbackLearner
from .core.query_analyzer import PreFlightQueryAnalyzer, QueryStatus
from .core.recon import (
    ContextSufficiencyEvaluator,
    MultiHopReconEngine,
    RelevanceScorer,
    SufficiencyScore,
    classify_investigation_mode,
)
from .core.relationships import RelationshipLinker, RelationshipReport
from .core.router import LayaDecisionRouter
from .core.symbols import extract_symbols_from_source
from .core.synthesizer import (
    ComparisonMatrixSynthesizer,
    ReadyToCodeSynthesizer,
)
from .extractor import QueryKeywordExtractor
from .llm import LLMError, solve
from .router import LayaRouter
from .schemas import (
    ComparisonMatrixPayload,
    DecisionRequest,
    InvestigationMode,
    InvestigationResult,
    QueryDomain,
    ReadyToCodePayload,
)
from .tools import (
    get_workspace_root,
    git_diff,
    git_log,
    git_status,
    read_file,
    run_tests,
    search_code,
    set_workspace_root,
)
from .traversal import HierarchicalExplorer

logger = logging.getLogger(__name__)

SEARCH_LIMIT = 6
FILE_LIMIT = 64
THRESHOLD = 0.70


@dataclass
class InvestigationState:
    evidence: list[str] = field(default_factory=list)
    searched_queries: set[str] = field(default_factory=set)
    read_files: set[str] = field(default_factory=set)
    discovered_symbols: set[str] = field(default_factory=set)
    declarations: list[DeclarationUnit] = field(default_factory=list)

    def text(self) -> str:
        return "\n\n".join(self.evidence)


def extract_paths(search_output: str) -> list[str]:
    paths: set[str] = set()
    for line in search_output.splitlines():
        match = re.match(
            r"^(.+?):\d+(?::\d+)?:",
            line,
        )
        if not match:
            continue
        path = match.group(1)
        path = path.removeprefix("./")
        if not any(
            excluded in path
            for excluded in [
                ".git",
                "node_modules",
                "__pycache__",
                ".venv",
                ".lock",
                ".codeprobe",
                ".gemini",
            ]
        ):
            paths.add(path)
    return sorted(paths)


def compact_search_result(query: str, result: str) -> str:
    lines = result.splitlines()
    truncated_lines = lines[:80]
    header = f"=== SEARCH: {query} ({len(lines)} matches) ===\n"
    return header + "\n".join(truncated_lines)


class Investigator:
    """
    Autonomous codebase investigation engine. Recursively explores files,
    git status, code symbols, and documentation until sufficient evidence
    is gathered to answer the user query or resolve the coding task.
    """

    def __init__(self) -> None:
        self.config = load_config()
        self.decision_router = LayaDecisionRouter(config=self.config)
        self.router = LayaRouter()

    def explore(
        self,
        query: str,
        target_files: list[str] | None = None,
        workspace_path: str | None = None,
        max_steps: int = 5,
        synthesize_summary: bool = True,
        mode: str | InvestigationMode = InvestigationMode.AUTO,
    ) -> InvestigationResult:
        """
        Execute an autonomous recursive investigation loop for a user query.
        Returns a rich InvestigationResult with findings, citations, and examined files.
        """
        investigation_id = FeedbackLearner.generate_investigation_id()

        # Determine dynamic workspace root
        prev_root = get_workspace_root()
        did_override = False
        if workspace_path:
            root_dir = set_workspace_root(workspace_path)
            did_override = True
        elif target_files and any(Path(f).is_absolute() for f in target_files):
            abs_f = next(Path(f) for f in target_files if Path(f).is_absolute())
            root_dir = set_workspace_root(abs_f if abs_f.is_dir() else abs_f.parent)
            did_override = True
        else:
            # Check if query itself references an existing absolute path on the filesystem
            found_ws = None
            for match in re.findall(
                r'(?:/(?:home|Users|var|tmp|opt|srv|etc|[A-Za-z]:\\)[^\s"\'`:]+)', query
            ):
                p = Path(match).resolve()
                if p.exists():
                    found_ws = p if p.is_dir() else p.parent
                    break
            if found_ws:
                root_dir = set_workspace_root(found_ws)
                did_override = True
            else:
                import os

                env_ws = (
                    os.environ.get("WORKSPACE_ROOT")
                    or os.environ.get("MCP_WORKSPACE_ROOT")
                    or os.environ.get("CODEPROBE_WORKSPACE")
                )
                if env_ws and Path(env_ws).exists():
                    root_dir = set_workspace_root(env_ws)
                else:
                    root_dir = get_workspace_root()

        # Check Git commit-aware semantic cache (0ms instant return if repository unchanged)
        cache = LocalEvidenceCache(Path(root_dir))
        cached_payload = cache.get_investigation(query=query, mode=str(mode))
        if cached_payload:
            try:
                cached_res = InvestigationResult.model_validate(cached_payload)
                if did_override:
                    set_workspace_root(prev_root)
                return cached_res
            except (ValueError, TypeError, KeyError) as exc:
                logger.debug("Failed to validate cached investigation: %s", exc)

        # Load calibrated learned weights from online feedback loop
        learned_weights = FeedbackLearner.load_learned_weights(root_dir)

        # 0. Pre-Flight Query Analysis & Ambiguity Clarification Gate (Step 0)
        query_analyzer = PreFlightQueryAnalyzer()
        analysis = query_analyzer.analyze(query, workspace_path=root_dir)

        if analysis.status == QueryStatus.NEEDS_CLARIFICATION:
            summary_msg = (
                f"### ⚠️ Query Clarification Needed\n\n"
                f"The query '{query}' is too ambiguous or lacks technical context (symbols, file paths, or error messages) "
                f"to perform targeted code reconnaissance.\n\n"
                f"**Questions to clarify your goal:**\n"
            )
            for i, q in enumerate(analysis.clarification_questions, 1):
                summary_msg += f"{i}. {q}\n"

            result = InvestigationResult(
                investigation_id=investigation_id,
                user_goal=query,
                strategy="NEEDS_CLARIFICATION",
                confidence=0.0,
                summary=summary_msg,
                actionable_guidance=(
                    "CRITICAL DIRECTIVE FOR AGENT: Do NOT explore the codebase arbitrarily. "
                    "Prompt the user with the clarification questions provided to obtain specific symbol/file context."
                ),
                suggested_next_actions=[
                    f"ask_user: {q}" for q in analysis.clarification_questions
                ],
                examined_files=[],
                discovered_symbols=[],
                is_sufficient=False,
                is_incomplete=False,
                steps_executed=0,
                evidence_snippets=[],
                retracted_files=[],
                cross_file_links=[],
                sufficiency_score=0.0,
                hop_count=0,
                missing_aspects=analysis.clarification_questions,
                verified_facts=[],
                unresolved_gaps=analysis.clarification_questions,
                exemplar_file=None,
                mounting_point=None,
                ready_to_code=None,
                mode=InvestigationMode.AUTO,
                comparison_matrix=None,
                needs_clarification=True,
                clarification_questions=analysis.clarification_questions,
            )
            if did_override:
                set_workspace_root(prev_root)
            return result

        state = InvestigationState()
        known_files: set[str] = set(target_files or [])
        if analysis.file_hints:
            known_files.update(analysis.file_hints)
        if analysis.target_symbols:
            state.discovered_symbols.update(analysis.target_symbols)

        # 1. Smart Token Extraction & Autonomous Multi-Hop Reconnaissance Engine (up to 6 hops)
        extracted_tokens = QueryKeywordExtractor.extract_search_tokens(query)
        if analysis.target_symbols:
            for s in analysis.target_symbols:
                if s not in extracted_tokens:
                    extracted_tokens.insert(0, s)
        discovered_paths = QueryKeywordExtractor.discover_workspace_paths(
            query, root_dir
        )
        known_files.update(discovered_paths)

        explorer = HierarchicalExplorer(root_dir, router=self.decision_router)
        recon_engine = MultiHopReconEngine(workspace_root=root_dir, config=self.config)
        recon_report = recon_engine.run(
            query=query,
            hierarchical_explorer=explorer,
            max_hops=min(max_steps, 6),
            threshold=0.80,
        )

        known_files.update(recon_report.candidate_files)
        is_incomplete_nav = recon_report.is_budget_exhausted

        # 2. Automatically check git status/logs if asking about status, progress, commits, or phases
        q_lower = query.lower()
        if any(
            k in q_lower
            for k in [
                "status",
                "progress",
                "tới đâu",
                "summary",
                "phase",
                "commit",
                "log",
                "tiến độ",
            ]
        ):
            phase_m = re.search(r"\d+(?:\.\d+)*", query)
            git_q = phase_m.group(0) if phase_m else ""
            self._git(state, git_q)

        # 3. Initial Search on extracted tokens
        for token in extracted_tokens[:SEARCH_LIMIT]:
            self._search(state, [token])

        # 4. Add files found from search results & recon report
        candidate_files = self._candidate_files(state)
        known_files.update(candidate_files)

        # Prioritize reading known and discovered files ranked by relevance & learned weights
        if known_files:
            ranked_files = self._rank_candidates(
                known_files, extracted_tokens, learned_weights
            )
            self._read_files(state, ranked_files[:FILE_LIMIT])

        # Merge declarations and symbols discovered by recon_report
        existing_decl_keys = {
            (d.file_path, d.name, d.start_line) for d in state.declarations
        }
        for decl in recon_report.declarations:
            if (decl.file_path, decl.name, decl.start_line) not in existing_decl_keys:
                state.declarations.append(decl)
                existing_decl_keys.add((decl.file_path, decl.name, decl.start_line))
        state.discovered_symbols.update(d.name for d in recon_report.declarations)
        state.discovered_symbols.update(recon_report.env_vars)

        # Record Recon Hops in evidence
        for hop in recon_report.hops:
            state.evidence.append(
                f"=== RECON HOP {hop.hop_number}: query='{hop.sub_query}' intent={hop.intent.value} sufficiency={hop.current_sufficiency:.2f} ==="
            )

        step_count = max(len(recon_report.hops), 1)
        is_sufficient = recon_report.final_score.is_sufficient

        if is_sufficient:
            state.evidence.append(
                f"=== SUFFICIENT EVIDENCE GATHERED (Hop {step_count}) ==="
            )
        else:
            # Fallback iterative exploration loop if context sufficiency threshold not yet met
            remaining_steps = max(0, max_steps - step_count)
            for step in range(remaining_steps):
                step_count += 1
                extracted_paths = list(known_files | self._candidate_files(state))
                req = DecisionRequest(
                    user_goal=query,
                    current_step=step,
                    collected_evidence=state.evidence[-8:],
                    known_files=extracted_paths[:20],
                    budget_remaining_steps=remaining_steps - step,
                )
                response = self.decision_router.route(req)
                if response.is_sufficient:
                    is_sufficient = True
                    state.evidence.append(
                        f"=== SUFFICIENT EVIDENCE GATHERED (Step {step_count}) ==="
                    )
                    break

                for rec_action in response.recommended_actions:
                    action_name = rec_action.action.value
                    if action_name in ("search_symbol", "grep_text"):
                        sub_query = rec_action.params.get("query", "")
                        if sub_query and sub_query != query:
                            sub_tokens = QueryKeywordExtractor.extract_search_tokens(
                                sub_query
                            )
                            self._search(state, sub_tokens)
                    elif action_name in ("read_file_slice", "read_full_file"):
                        candidates = rec_action.params.get(
                            "candidate_files", []
                        ) or list(self._candidate_files(state))
                        self._read_files(state, candidates)
                    elif action_name in ("git_status", "git_diff", "git_log"):
                        self._git(state, query if "log" in action_name else "")
                    elif action_name == "run_tests":
                        self._tests(state)

        # 6. Analyze cross-file relationships and filter out false positives
        all_examined_files = sorted(state.read_files)
        rel_report = RelationshipLinker.trace_relationships(
            declarations=state.declarations,
            all_candidate_files=all_examined_files,
            query_tokens=extracted_tokens,
        )

        active_files = [
            f for f in all_examined_files if f not in rel_report.retracted_files
        ] or all_examined_files

        if recon_report.decomposed.domain == QueryDomain.INFRA_DEVOPS:

            def _infra_priority(f: str) -> int:
                f_low = f.lower()
                if any(
                    ext in f_low
                    for ext in (".sh", ".bash", ".yaml", ".yml", "dockerfile")
                ):
                    return 0
                if any(
                    part in f_low
                    for part in (
                        "backup",
                        "dr",
                        "deploy",
                        "k8s",
                        "docker",
                        "compose",
                        "infra",
                        "scripts",
                    )
                ):
                    return 1
                if any(
                    part in f_low
                    for part in ("test", "services", "models", "views", "serializers")
                ):
                    return 3
                return 2

            active_files.sort(key=_infra_priority)
            state.declarations.sort(key=lambda d: _infra_priority(d.file_path))

        # 7. Final Context Sufficiency Check on consolidated state
        cross_links = [
            f"{link.caller_unit} ({link.source_file}) ──calls──> {link.target_symbol} ({link.target_file})"
            for link in rel_report.links
        ]
        consolidated_score = ContextSufficiencyEvaluator.evaluate(
            decomposed=recon_report.decomposed,
            candidate_files=active_files,
            declarations=state.declarations,
            cross_file_links=cross_links,
            discovered_env_vars=recon_report.env_vars,
            found_config_files=recon_report.config_files,
            threshold=0.80,
        )

        final_score = (
            consolidated_score
            if consolidated_score.total_score >= recon_report.final_score.total_score
            else recon_report.final_score
        )
        is_sufficient = is_sufficient or final_score.is_sufficient

        if recon_report.decomposed.is_scaffold:
            strategy = "NEW_FEATURE_SCAFFOLD"
        elif is_sufficient:
            strategy = "READY_TO_SYNTHESIZE"
        else:
            strategy = "INSPECT_SOURCE"

        confidence = round(
            max(final_score.total_score, 0.50 if active_files else 0.10), 2
        )
        if is_sufficient:
            suggested_actions = [
                "synthesize_answer: Formulate final solution with gathered repository evidence."
            ]
        else:
            suggested_actions = [
                f"investigate_further: Address missing {m}"
                for m in final_score.missing_aspects
            ]

        investigation_mode = (
            mode
            if isinstance(mode, InvestigationMode) and mode != InvestigationMode.AUTO
            else classify_investigation_mode(query, explicit_mode=mode)
        )

        ready_to_code_payload: ReadyToCodePayload | None = None
        comparison_matrix_payload: ComparisonMatrixPayload | None = None

        if investigation_mode == InvestigationMode.AUDIT_COMPARE:
            comparison_matrix_payload = ComparisonMatrixSynthesizer.synthesize(
                query=query,
                examined_files=active_files,
                declarations=state.declarations,
                workspace_root=root_dir,
            )
        elif investigation_mode == InvestigationMode.CODE_MODIFICATION:
            ready_to_code_payload = ReadyToCodeSynthesizer.synthesize(
                query=query,
                examined_files=active_files,
                declarations=state.declarations,
                recon_report=recon_report,
                relationship_report=rel_report,
                workspace_root=root_dir,
                mode=investigation_mode,
            )

        evidence_full_text = state.text()
        evidence_mgr = EvidenceManager()
        for decl in state.declarations:
            evidence_mgr.add(
                source=decl.file_path,
                content=decl.signature,
                kind="source_code",
                line_start=decl.start_line,
                line_end=decl.end_line,
                status="FACT",
            )
        for cf in recon_report.config_files:
            evidence_mgr.add(source=cf, content="Discovered config file", kind="config_entry", status="FACT")
        for missing in final_score.missing_aspects:
            evidence_mgr.add(source="recon_analysis", content=missing, kind="command_output", status="GAP")

        verified_fact_strs = [
            f"{f.source}:{f.line_start}-{f.line_end} [{f.kind}]" if f.line_start else f"{f.source} [{f.kind}]"
            for f in evidence_mgr.facts()
        ]
        unresolved_gap_strs = [g.content for g in evidence_mgr.gaps()]

        summary_text = ""
        if synthesize_summary:
            summary_text = self._synthesize_answer(
                query,
                evidence_full_text,
                active_files,
                declarations=state.declarations,
                relationship_report=rel_report,
                sufficiency_score=final_score,
                hop_count=step_count,
                comparison_matrix=comparison_matrix_payload,
                evidence_manager=evidence_mgr,
            )

        result = InvestigationResult(
            investigation_id=investigation_id,
            user_goal=query,
            strategy=strategy,
            confidence=confidence,
            summary=summary_text,
            actionable_guidance="CRITICAL DIRECTIVE FOR AGENT: Use the above synthesized findings directly to complete the user request. Do NOT discard this evidence or re-explore the codebase from scratch.",
            suggested_next_actions=suggested_actions,
            examined_files=active_files,
            discovered_symbols=sorted(state.discovered_symbols)[:30],
            is_sufficient=is_sufficient,
            is_incomplete=is_incomplete_nav,
            steps_executed=step_count,
            evidence_snippets=state.evidence[-10:],
            retracted_files=rel_report.retracted_files,
            cross_file_links=cross_links,
            sufficiency_score=final_score.total_score,
            hop_count=step_count,
            missing_aspects=final_score.missing_aspects,
            verified_facts=verified_fact_strs,
            unresolved_gaps=unresolved_gap_strs,
            exemplar_file=final_score.exemplar_file,
            mounting_point=final_score.mounting_point,
            ready_to_code=ready_to_code_payload,
            mode=investigation_mode,
            comparison_matrix=comparison_matrix_payload,
        )

        # Log trajectory for self-training online feedback loop
        FeedbackLearner.record_trajectory(result, root_dir)

        # Store in Git commit-aware cache and last_investigation.json
        try:
            cache.set_investigation(query=query, mode=str(mode), data=result.model_dump())
            last_file = Path(root_dir) / ".codeprobe" / "last_investigation.json"
            last_file.parent.mkdir(parents=True, exist_ok=True)
            last_file.write_text(json.dumps(result.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
        except (OSError, ValueError, TypeError) as exc:
            logger.debug("Failed to store investigation cache: %s", exc)

        if did_override:
            set_workspace_root(prev_root)

        return result

    def _synthesize_answer(
        self,
        query: str,
        evidence: str,
        examined_files: list[str],
        declarations: list[DeclarationUnit] | None = None,
        relationship_report: RelationshipReport | None = None,
        sufficiency_score: SufficiencyScore | None = None,
        hop_count: int = 1,
        comparison_matrix: ComparisonMatrixPayload | None = None,
        evidence_manager: EvidenceManager | None = None,
    ) -> str:
        """
        Synthesize answer using local/remote LLM, combining reasoned response
        with structured deterministic synthesis and evidence provenance.
        """
        structured_meta = self._deterministic_fallback_synthesis(
            query,
            evidence,
            examined_files,
            declarations=declarations,
            relationship_report=relationship_report,
            sufficiency_score=sufficiency_score,
            hop_count=hop_count,
            comparison_matrix=comparison_matrix,
        )
        try:
            compact_ctx = (
                evidence_manager.export_compact_summary()
                if evidence_manager
                else evidence[-8_000:]
            )
            llm_text = solve(user_request=query, context=compact_ctx, timeout=60)
            return f"{llm_text.strip()}\n\n{structured_meta}"
        except (LLMError, OSError, ValueError, RuntimeError) as exc:
            logger.debug(
                "LLM solve not available (%s), using structured fallback synthesis.",
                exc,
            )
            return structured_meta

    def _deterministic_fallback_synthesis(
        self,
        query: str,
        evidence: str,
        examined_files: list[str],
        declarations: list[DeclarationUnit] | None = None,
        relationship_report: RelationshipReport | None = None,
        sufficiency_score: SufficiencyScore | None = None,
        hop_count: int = 1,
        comparison_matrix: ComparisonMatrixPayload | None = None,
    ) -> str:
        lines: list[str] = [
            f"### Investigation Findings for: '{query}'\n",
        ]

        if comparison_matrix:
            lines.append("#### ⚖️ Comparison Matrix & Feature Parity:")
            lines.append(
                f"- **Subsystems Detected:** {', '.join(comparison_matrix.subsystems_detected)}"
            )
            lines.append("")
            lines.append(
                "| Domain | Source Component | Target Component | Parity Status | Missing Capabilities |"
            )
            lines.append("|---|---|---|---|---|")
            for pair in comparison_matrix.component_pairs:
                missing_str = (
                    ", ".join(pair.missing_in_target)
                    if pair.missing_in_target
                    else "None (Full Parity)"
                )
                lines.append(
                    f"| `{pair.aspect}` | `{pair.source_component}` | `{pair.target_component}` | **{pair.parity_status}** | {missing_str} |"
                )
            lines.append("")
            if comparison_matrix.architectural_gaps:
                lines.append("**Architectural Gaps:**")
                for gap in comparison_matrix.architectural_gaps:
                    lines.append(f"- {gap}")
                lines.append("")

        if sufficiency_score is not None:
            lines.append("#### 🎯 Reconnaissance & Context Sufficiency:")
            lines.append(
                f"- **Sufficiency Score:** {sufficiency_score.total_score * 100:.0f}% ({'Sufficient' if sufficiency_score.is_sufficient else 'Incomplete'})"
            )
            lines.append(f"- **Autonomous Hops:** {hop_count}")
            lines.append(
                f"- **Dimension Scores:** Target Files `{sufficiency_score.target_file_score:.2f}` | Anchor Code `{sufficiency_score.anchor_code_score:.2f}` | Callers/Deps `{sufficiency_score.callers_score:.2f}` | Config/Env `{sufficiency_score.config_score:.2f}`"
            )
            if sufficiency_score.mounting_point:
                lines.append(
                    f"- **Mounting Point (Router/Entrypoint):** `{sufficiency_score.mounting_point}`"
                )
            if sufficiency_score.exemplar_file:
                lines.append(
                    f"- **Exemplar Donor File:** `{sufficiency_score.exemplar_file}`"
                )
            if sufficiency_score.missing_aspects:
                lines.append(
                    f"- **Missing Aspects:** {', '.join(sufficiency_score.missing_aspects)}"
                )
            lines.append("")

        plan_summaries: list[dict[str, str]] = []
        file_snippets: list[str] = []
        git_snippets: list[str] = []

        for block in evidence.split("=== "):
            block = block.strip()
            if not block:
                continue
            lines_in_block = block.splitlines()
            title = lines_in_block[0].replace("===", "").strip()
            content = "\n".join(lines_in_block[1:]).strip()

            if title.startswith("FILE:"):
                file_path = title.replace("FILE:", "").strip()
                is_plan_or_summary = any(
                    k in file_path.upper()
                    for k in ["PLAN.MD", "SUMMARY.MD", "VERIFICATION.MD"]
                )

                status_match = re.search(r"(?m)^status:\s*([a-zA-Z_\-]+)", content)
                wave_match = re.search(r"(?m)^wave:\s*([a-zA-Z0-9_\-]+)", content)
                phase_match = re.search(r"(?m)^phase:\s*([a-zA-Z0-9_\-\.]+)", content)
                objective_match = re.search(
                    r"<objective>(.*?)</objective>", content, re.DOTALL
                )

                if is_plan_or_summary and (status_match or wave_match or phase_match):
                    status_val = status_match.group(1) if status_match else "unknown"
                    wave_val = wave_match.group(1) if wave_match else "-"
                    phase_val = phase_match.group(1) if phase_match else "-"
                    obj_text = ""
                    if objective_match:
                        obj_clean = re.sub(
                            r"\s+", " ", objective_match.group(1)
                        ).strip()
                        obj_text = (
                            obj_clean[:140] + "..."
                            if len(obj_clean) > 140
                            else obj_clean
                        )

                    plan_summaries.append(
                        {
                            "file": Path(file_path).name,
                            "phase": phase_val,
                            "wave": wave_val,
                            "status": status_val.upper(),
                            "objective": obj_text,
                        }
                    )
                else:
                    first_lines = "\n".join(content.splitlines()[:15])
                    file_snippets.append(
                        f"**FILE: {file_path}**:\n```markdown\n{first_lines}\n```"
                    )

            elif title.startswith("GIT"):
                first_lines = "\n".join(content.splitlines()[:15])
                git_snippets.append(f"**{title}**:\n```\n{first_lines}\n```")

        if plan_summaries:
            # Sort plans by filename (e.g. 12.1-01, 12.1-02, ...)
            plan_summaries.sort(key=lambda x: x["file"])
            lines.append("#### 📋 Phase Execution & Plans Status:")
            lines.append("| Plan File | Phase | Wave | Status | Objective / Scope |")
            lines.append("| :--- | :--- | :--- | :--- | :--- |")
            for ps in plan_summaries:
                lines.append(
                    f"| `{ps['file']}` | {ps['phase']} | {ps['wave']} | **`{ps['status']}`** | {ps['objective']} |"
                )
            lines.append("")

        if git_snippets:
            lines.append("#### 🪵 Git Activity & Commits:")
            lines.extend(git_snippets[:2])
            lines.append("")

        if file_snippets:
            lines.append("#### 🔍 Key Document Extracts:")
            lines.extend(file_snippets[:4])
            lines.append("")

        # Tier 2: Structural Declaration Units (Filtered & Ranked by RelevanceScorer)
        if declarations:
            relevant_decls = RelevanceScorer.filter_and_rank_declarations(
                declarations, query, threshold=0.40, top_k=6
            )
            if relevant_decls:
                lines.append("#### 🧩 Key Declaration Units:")
                for decl in relevant_decls:
                    lines.append(f"```\n{decl.format_verbatim()}\n```")
                lines.append("")

        # Tier 3: Cross-File Relationships & Retraction Audit
        if relationship_report and (
            relationship_report.links or relationship_report.retracted_files
        ):
            lines.append("#### 🔗 Relationships & Evidence Audit:")
            lines.append(relationship_report.format_summary())
            lines.append("")

        lines.append(f"**Examined Files ({len(examined_files)}):**")
        for f in examined_files[:12]:
            lines.append(f"- `{f}`")

        return "\n".join(lines)

    def _search(self, state: InvestigationState, queries: list[str]) -> None:
        for query in queries[:SEARCH_LIMIT]:
            query = query.strip()
            if not query or query in state.searched_queries:
                continue
            state.searched_queries.add(query)
            try:
                result = search_code(query)
            except (OSError, RuntimeError) as exc:
                state.evidence.append(f"=== SEARCH ERROR: {query} ===\n{exc}")
                continue
            if result.strip():
                state.evidence.append(compact_search_result(query, result))

    def _read_files(self, state: InvestigationState, candidates: list[str]) -> None:
        for path in candidates[:FILE_LIMIT]:
            if not path or path in state.read_files:
                continue
            if self.config.is_file_forbidden(path):
                continue
            state.read_files.add(path)
            try:
                content = read_file(path)
            except (OSError, UnicodeDecodeError) as exc:
                state.evidence.append(f"=== FILE ERROR: {path} ===\n{exc}")
                continue

            # Extract possible symbols across Python, TypeScript/JS, Rust, Go
            syms = extract_symbols_from_source(content, path)
            state.discovered_symbols.update(syms)

            # Parse structural declaration units (AST / structural blocks)
            decls = DeclarationParser.parse(content, path)
            state.declarations.extend(decls)

            state.evidence.append(f"=== FILE: {path} ===\n{content[:8000]}")

    def _git(self, state: InvestigationState, git_query: str = "") -> None:
        try:
            st = git_status()
            if st.strip():
                state.evidence.append("=== GIT STATUS ===\n" + st)
        except (OSError, RuntimeError) as exc:
            logger.debug("git_status failed: %s", exc)

        try:
            df = git_diff()
            if df.strip():
                state.evidence.append("=== GIT DIFF ===\n" + df[:3000])
        except (OSError, RuntimeError) as exc:
            logger.debug("git_diff failed: %s", exc)

        if git_query:
            try:
                gl = git_log(git_query)
                if gl.strip():
                    state.evidence.append(f"=== GIT LOG: {git_query} ===\n" + gl)
            except (OSError, RuntimeError) as exc:
                logger.debug("git_log failed: %s", exc)

    def _schema(self, state: InvestigationState) -> None:
        queries = [
            r"class .*models\.Model",
            r"ForeignKey",
            r"OneToOneField",
            r"ManyToManyField",
            r"models\.CASCADE",
        ]
        for query in queries:
            if query in state.searched_queries:
                continue
            state.searched_queries.add(query)
            result = search_code(query)
            if result.strip():
                state.evidence.append(compact_search_result(f"SCHEMA: {query}", result))

    def _tests(self, state: InvestigationState) -> None:
        try:
            state.evidence.append("=== TESTS ===\n" + run_tests())
        except (OSError, RuntimeError) as exc:
            state.evidence.append(f"=== TESTS ERROR ===\n{exc}")

    def _candidate_files(self, state: InvestigationState) -> set[str]:
        candidates: set[str] = set()
        for evidence in state.evidence:
            if "=== SEARCH:" not in evidence:
                continue
            candidates.update(extract_paths(evidence))
        return candidates

    @staticmethod
    def _rank_candidates(
        candidates: set[str] | list[str],
        tokens: list[str],
        learned_weights: dict[str, Any] | None = None,
    ) -> list[str]:
        scored: list[tuple[int, str]] = []
        token_lowers = [t.lower() for t in tokens if len(t) >= 2]
        weights = learned_weights or {}
        path_boosts = weights.get("path_boosts", {})
        ext_boosts = weights.get("ext_boosts", {})
        negative_patterns = weights.get("negative_patterns", [])

        for path in candidates:
            score = 0
            path_lower = path.lower()
            p_obj = Path(path)
            name_lower = p_obj.name.lower()
            ext = p_obj.suffix.lower()

            for t in token_lowers:
                if t in name_lower:
                    score += 30
                elif t in path_lower:
                    score += 15

            # Apply learned online path boosts
            for pattern, multiplier in path_boosts.items():
                if pattern.lower() in path_lower:
                    score += int(multiplier * 10)

            # Apply learned online extension boosts
            if ext in ext_boosts:
                score += int(ext_boosts[ext] * 8)

            # Apply negative pattern penalty
            for neg in negative_patterns:
                if neg.lower() in path_lower:
                    score -= 30

            # Prioritize summary, state, roadmap, plan files
            if "summary.md" in name_lower or "state.md" in name_lower:
                score += 25
            elif "roadmap.md" in name_lower:
                score += 20
            elif "plan.md" in name_lower:
                score += 18
            elif "context.md" in name_lower:
                score += 15
            elif ".planning" in path_lower:
                score += 10

            # Deprioritize ancillary / noise files
            if "windows.md" in name_lower:
                score -= 10
            if "test" in path_lower and not any("test" in t for t in token_lowers):
                score -= 5

            scored.append((score, path))

        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [path for _, path in scored]

    # Legacy backward-compatible signature
    def investigate(
        self, *, initial_plan: dict, max_steps: int = 8
    ) -> InvestigationState:
        query = " ".join(initial_plan.get("search_queries", [])) or "investigation"
        known_files = initial_plan.get("files_to_read", [])
        res = self.explore(
            query=query,
            target_files=known_files,
            max_steps=max_steps,
            synthesize_summary=False,
        )
        st = InvestigationState()
        st.evidence = res.evidence_snippets
        st.read_files = set(res.examined_files)
        return st
