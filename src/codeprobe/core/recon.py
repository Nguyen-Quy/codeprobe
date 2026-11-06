from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from ..config import ProjectConfig, load_config
from ..schemas import DeclarationUnit, InvestigationMode, QueryDomain
from .declarations import DeclarationParser
from .relationships import RelationshipLinker, RelationshipReport

logger = logging.getLogger(__name__)


def classify_investigation_mode(
    query: str, explicit_mode: str | InvestigationMode | None = None
) -> InvestigationMode:
    """
    Classifies user investigation intent into InvestigationMode:
    - AUDIT_COMPARE: comparison, parity, gap analysis, survey of differences
    - CODE_MODIFICATION: fix, refactor, add, implement, patch, optimize
    - SURVEY_EXPLORATION: symbol location, explain, trace, fact-finding
    """
    if explicit_mode:
        if isinstance(explicit_mode, InvestigationMode):
            if explicit_mode != InvestigationMode.AUTO:
                return explicit_mode
        elif isinstance(explicit_mode, str):
            val = explicit_mode.strip().lower()
            if val in ("code", "code_modification", "modify", "edit"):
                return InvestigationMode.CODE_MODIFICATION
            if val in ("compare", "audit", "audit_compare", "diff"):
                return InvestigationMode.AUDIT_COMPARE
            if val in ("survey", "survey_exploration", "explore"):
                return InvestigationMode.SURVEY_EXPLORATION

    q_lower = query.lower()

    # Compare / Audit keywords (highest precedence when user asks to compare/contrast)
    compare_keywords = [
        "so sánh",
        "so sanh",
        "đối chiếu",
        "doi chieu",
        "compare",
        "comparison",
        "audit",
        "thiếu gì",
        "thieu gi",
        "chênh lệch",
        "chenh lech",
        "gap analysis",
        "feature parity",
        "có thiếu",
        "co thieu",
        "vs",
        "versus",
    ]
    if any(k in q_lower for k in compare_keywords):
        return InvestigationMode.AUDIT_COMPARE

    # Code modification keywords
    code_keywords = [
        "sửa",
        "sua",
        "fix",
        "refactor",
        "tối ưu",
        "toi uu",
        "optimize",
        "implement",
        "thêm code",
        "them code",
        "patch",
        "chỉnh sửa",
        "chinh sua",
        "update code",
        "cập nhật",
        "cap nhat",
        "rewrite",
        "scaffold",
    ]
    if any(k in q_lower for k in code_keywords):
        return InvestigationMode.CODE_MODIFICATION

    # Match standalone English command verbs
    if re.search(r"\b(?:add|update|modify|edit|fix|patch|refactor|create)\b", q_lower):
        return InvestigationMode.CODE_MODIFICATION

    return InvestigationMode.SURVEY_EXPLORATION


class RelevanceScorer:
    """
    Computes keyword & semantic relevance scores for DeclarationUnit symbols against user query.
    Applies threshold cutoff (>= 0.40) and returns top-K relevant declarations.
    """

    BOOST_KEYWORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "deploy",
            "backup",
            "restore",
            "failover",
            "failback",
            "dr",
            "drill",
            "sync",
            "migrate",
            "migration",
            "auth",
            "login",
            "register",
            "verify",
            "health",
            "reconcile",
            "execute",
            "synthesize",
            "extract",
            "parse",
        }
    )

    @classmethod
    def score_declaration(cls, decl: DeclarationUnit, query: str) -> float:
        from .declarations import GENERIC_ENV_BLACKLIST, NOISE_FUNCTION_BLACKLIST

        name_lower = decl.name.lower()
        if (
            name_lower in NOISE_FUNCTION_BLACKLIST
            or decl.name.upper() in GENERIC_ENV_BLACKLIST
        ):
            return 0.0

        STOP_WORDS = frozenset(
            {
                "and",
                "or",
                "the",
                "in",
                "on",
                "at",
                "to",
                "for",
                "with",
                "va",
                "và",
                "cua",
                "của",
                "cho",
                "o",
                "ở",
            }
        )
        q_tokens = {
            t
            for t in re.findall(r"[a-zA-Z0-9]{2,}", query.lower())
            if t not in STOP_WORDS
        }
        if not q_tokens:
            return 0.50

        decl_name_tokens = set(re.findall(r"[a-zA-Z0-9]{2,}", name_lower))
        sig_tokens = set(re.findall(r"[a-zA-Z0-9]{2,}", decl.signature.lower()))
        doc_tokens = (
            set(re.findall(r"[a-zA-Z0-9]{2,}", decl.docstring.lower()))
            if decl.docstring
            else set()
        )

        name_match = len(q_tokens & decl_name_tokens) / max(len(decl_name_tokens), 1)
        sig_match = len(q_tokens & sig_tokens) / max(len(sig_tokens), 1)
        doc_match = (
            len(q_tokens & doc_tokens) / max(len(doc_tokens), 1) if doc_tokens else 0.0
        )

        raw_score = (name_match * 0.50) + (sig_match * 0.30) + (doc_match * 0.20)

        # Boost if name contains action keywords
        if any(b in decl_name_tokens for b in cls.BOOST_KEYWORDS):
            raw_score = min(1.0, raw_score * 1.5 + 0.20)

        # Exact token match bonus
        if any(t in decl_name_tokens for t in q_tokens) or name_lower in query.lower():
            raw_score = max(raw_score, 0.60)

        return round(raw_score, 3)

    @classmethod
    def filter_and_rank_declarations(
        cls,
        declarations: list[DeclarationUnit],
        query: str,
        threshold: float = 0.40,
        top_k: int = 6,
    ) -> list[DeclarationUnit]:
        scored: list[tuple[float, DeclarationUnit]] = []
        for d in declarations:
            s = cls.score_declaration(d, query)
            if s >= threshold:
                scored.append((s, d))
        # Sort descending by score
        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:top_k]]


class GoalIntent(str, Enum):
    CODE_LOGIC = "code_logic"
    INFRA_CONFIG = "infra_config"
    ERROR_TRACE = "error_trace"
    ARCHITECTURE = "architecture"
    PLANNING = "planning"
    NEW_FEATURE_SCAFFOLD = "new_feature_scaffold"


@dataclass
class DecomposedGoal:
    original_query: str
    intent: GoalIntent
    primary_symbols: list[str] = field(default_factory=list)
    env_var_tokens: list[str] = field(default_factory=list)
    error_tokens: list[str] = field(default_factory=list)
    target_path_hints: list[str] = field(default_factory=list)
    is_scaffold: bool = False
    domain: QueryDomain = QueryDomain.APPLICATION_LOGIC


class GoalDecomposer:
    """
    Decomposes user query into intent and target tokens offline (0 LLM tokens).
    """

    SCAFFOLD_KEYWORDS: ClassVar[list[str]] = [
        "thêm",
        "tao moi",
        "tạo mới",
        "cài thêm",
        "viết mới",
        "xây dựng",
        "add new",
        "create new",
        "implement new",
        "scaffold",
        "new feature",
        "introduce",
        "build new",
        "register new",
    ]

    ERROR_KEYWORDS: ClassVar[list[str]] = [
        "error",
        "exception",
        "traceback",
        "failed",
        "crash",
        "bug",
        "lỗi",
        "typeerror",
        "valueerror",
        "indexerror",
        "keyerror",
        "nullpointer",
    ]

    INFRA_KEYWORDS: ClassVar[list[str]] = [
        "k8s",
        "kubernetes",
        "docker",
        "compose",
        "networkpolicy",
        "nginx",
        "caddy",
        "yaml",
        "yml",
        "secret",
        "cronjob",
        "pvc",
        "deployment",
        "ingress",
        "helm",
        "kustomize",
        "backup",
        "disaster recovery",
        "disaster",
        "failover",
        "failback",
        "restore",
        "restic",
        "pg_dump",
        "postgres dump",
        "systemd",
        "timer",
        "bash",
        "shell",
        "s3",
        "r2",
        "cloudflare r2",
    ]

    SHORT_INFRA_WORDS: ClassVar[set[str]] = {
        "k8s",
        "dr",
        "sh",
        "r2",
        "s3",
        "env",
        "yml",
    }

    PLANNING_KEYWORDS: ClassVar[list[str]] = [
        ".planning",
        "phase",
        "roadmap",
        "state",
        "summary",
        "milestone",
        "tiến độ",
        "kế hoạch",
    ]

    @classmethod
    def _matches_any(cls, keywords: list[str], text: str) -> bool:
        for k in keywords:
            if k in cls.SHORT_INFRA_WORDS or len(k) <= 3:
                if re.search(rf"\b{re.escape(k)}\b", text):
                    return True
            else:
                if k in text:
                    return True
        return False

    @classmethod
    def decompose(cls, query: str) -> DecomposedGoal:
        q_lower = query.lower()

        # 1. Determine Intent & Domain
        is_scaffold = any(k in q_lower for k in cls.SCAFFOLD_KEYWORDS)
        is_error = any(k in q_lower for k in cls.ERROR_KEYWORDS)
        is_infra = cls._matches_any(
            cls.INFRA_KEYWORDS + list(cls.SHORT_INFRA_WORDS), q_lower
        )
        is_planning = any(k in q_lower for k in cls.PLANNING_KEYWORDS)

        if is_scaffold:
            intent = GoalIntent.NEW_FEATURE_SCAFFOLD
        elif is_error:
            intent = GoalIntent.ERROR_TRACE
        elif is_planning:
            intent = GoalIntent.PLANNING
        elif is_infra:
            intent = GoalIntent.INFRA_CONFIG
        else:
            intent = GoalIntent.CODE_LOGIC

        # Classify Domain
        if is_infra:
            domain = QueryDomain.HYBRID if is_error else QueryDomain.INFRA_DEVOPS
        elif is_planning:
            domain = QueryDomain.APPLICATION_LOGIC
        else:
            domain = QueryDomain.APPLICATION_LOGIC

        # 2. Extract Env Var Tokens (UPPERCASE_WITH_UNDERSCORES, length >= 4)
        env_vars = re.findall(r"\b[A-Z][A-Z0-9_]{3,}\b", query)
        # Filter out common shouting false positives
        env_vars = [
            v
            for v in env_vars
            if v
            not in (
                "HTTP",
                "JSON",
                "REST",
                "POST",
                "GET",
                "PUT",
                "TRUE",
                "FALSE",
                "NULL",
                "NONE",
            )
        ]

        # 3. Extract Error tokens
        error_tokens = []
        for line in query.splitlines():
            for m in re.finditer(r"\b(\w*Error|\w*Exception)\b", line):
                error_tokens.append(m.group(1))

        # 4. Extract symbols (CamelCase, snake_case)
        symbols = []
        for word in re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b", query):
            if word in env_vars or word in error_tokens:
                continue
            # Keep CamelCase or snake_case with underscores
            if ("_" in word and not word.startswith("__")) or (
                re.search(r"[a-z][A-Z]", word)
            ):
                symbols.append(word)

        # 5. Extract path hints (e.g. src/auth, .planning/phases)
        paths = re.findall(
            r"(?:[a-zA-Z0-9_\-.]+/)+[a-zA-Z0-9_\-.]*(?:\.[a-zA-Z0-9]+)?", query
        )

        return DecomposedGoal(
            original_query=query,
            intent=intent,
            primary_symbols=symbols,
            env_var_tokens=env_vars,
            error_tokens=error_tokens,
            target_path_hints=paths,
            is_scaffold=is_scaffold,
            domain=domain,
        )


@dataclass
class SufficiencyScore:
    target_file_score: float = 0.0  # max 0.30
    anchor_code_score: float = 0.0  # max 0.30
    callers_score: float = 0.0  # max 0.20
    config_score: float = 0.0  # max 0.20
    total_score: float = 0.0  # max 1.0
    is_sufficient: bool = False
    missing_aspects: list[str] = field(default_factory=list)
    target_file: str | None = None
    mounting_point: str | None = None
    exemplar_file: str | None = None

    def calculate_total(self, threshold: float = 0.80) -> float:
        self.total_score = round(
            min(
                1.0,
                self.target_file_score
                + self.anchor_code_score
                + self.callers_score
                + self.config_score,
            ),
            2,
        )
        self.is_sufficient = self.total_score >= threshold
        return self.total_score


class ContextSufficiencyEvaluator:
    """
    Evaluates whether gathered evidence satisfies the 4 core dimensions required
    for an AI coding agent to implement or fix code without re-searching.
    """

    MOUNTING_FILENAMES = (
        "urls.py",
        "routes.py",
        "router.py",
        "routes.ts",
        "router.ts",
        "__init__.py",
        "index.ts",
        "index.js",
        "main.py",
        "app.py",
        "server.py",
        "app.ts",
        "server.ts",
        "main.go",
        "lib.rs",
        "main.rs",
    )

    @classmethod
    def evaluate(
        cls,
        decomposed: DecomposedGoal,
        candidate_files: list[str],
        declarations: list[DeclarationUnit],
        cross_file_links: list[str],
        discovered_env_vars: set[str],
        found_config_files: list[str],
        threshold: float = 0.80,
    ) -> SufficiencyScore:
        score = SufficiencyScore()
        missing: list[str] = []

        if not candidate_files:
            score.missing_aspects = ["target_file", "code_anchor", "callers", "configs"]
            score.calculate_total(threshold)
            return score

        # -------------------------------------------------------------
        # Case A: NEW_FEATURE_SCAFFOLD (Dual Anchor: Mounting Point + Exemplar)
        # -------------------------------------------------------------
        if decomposed.is_scaffold:
            # 1. Look for mounting/registration point
            mounting_candidate = None
            for f in candidate_files:
                name = Path(f).name.lower()
                if name in cls.MOUNTING_FILENAMES:
                    mounting_candidate = f
                    break

            if mounting_candidate:
                score.target_file_score = 0.30
                score.mounting_point = mounting_candidate
            else:
                score.target_file_score = 0.15
                missing.append("mounting_point")

            # 2. Look for exemplar donor template in sibling files
            exemplar_candidate = None
            for f in candidate_files:
                if f != mounting_candidate and any(
                    f.endswith(ext) for ext in (".py", ".ts", ".js", ".go", ".rs")
                ):
                    exemplar_candidate = f
                    break

            if exemplar_candidate:
                score.anchor_code_score = 0.30
                score.exemplar_file = exemplar_candidate
            else:
                score.anchor_code_score = 0.15
                missing.append("exemplar_donor_template")

            # 3. Callers / dependencies for new features
            if cross_file_links or len(candidate_files) >= 2:
                score.callers_score = 0.20
            else:
                score.callers_score = 0.10

            # 4. Configs
            if discovered_env_vars or found_config_files:
                score.config_score = 0.20
            else:
                score.config_score = 0.15

            score.missing_aspects = missing
            score.target_file = score.mounting_point or (
                candidate_files[0] if candidate_files else None
            )
            score.calculate_total(threshold)
            return score

        # -------------------------------------------------------------
        # Case B: BUG_FIX_OR_EDIT / CODE_LOGIC / INFRA
        # -------------------------------------------------------------
        # 1. Target File Identified (+0.30)
        target_f = None
        if decomposed.domain == QueryDomain.INFRA_DEVOPS:
            # Prioritize infrastructure files (scripts, YAML, docker, k8s, backup, DR)
            infra_candidates = [
                f
                for f in candidate_files
                if DeclarationParser.is_infra_file(f)
                or any(
                    part in f.lower()
                    for part in (
                        "script",
                        "deploy",
                        "backup",
                        "k8s",
                        "docker",
                        "compose",
                        "infra",
                        "dr",
                    )
                )
            ]
            if infra_candidates:
                target_f = infra_candidates[0]

        if not target_f and candidate_files:
            target_f = candidate_files[0]

        if target_f:
            score.target_file_score = 0.30
            score.target_file = target_f
        else:
            missing.append("target_file")

        # 2. Exact Code Anchor with line numbers (+0.30)
        has_anchor = False
        non_infra_anchor_found = False
        valid_anchor_kinds = (
            "function",
            "class",
            "method",
            "interface",
            "struct",
            "trait",
            "handler",
            "argument",
            "infra",
            "k8s_resource",
            "docker_service",
            "env_var",
            "shell_script",
        )

        for decl in declarations:
            if (
                decl.start_line > 0
                and decl.end_line >= decl.start_line
                and decl.kind in valid_anchor_kinds
            ):
                if decomposed.domain == QueryDomain.INFRA_DEVOPS:
                    is_infra = DeclarationParser.is_infra_file(decl.file_path) or any(
                        part in decl.file_path.lower()
                        for part in (
                            "script",
                            "deploy",
                            "backup",
                            "k8s",
                            "docker",
                            "compose",
                            "infra",
                            "dr",
                        )
                    )
                    if is_infra:
                        has_anchor = True
                        break
                    else:
                        non_infra_anchor_found = True
                else:
                    has_anchor = True
                    break

        if has_anchor:
            score.anchor_code_score = 0.30
        elif non_infra_anchor_found and decomposed.domain == QueryDomain.INFRA_DEVOPS:
            # Domain weighted penalty: App anchor on Infra query gets confidence penalty
            score.anchor_code_score = 0.10
            missing.append("infra_specific_code_anchor")
        elif declarations:
            score.anchor_code_score = 0.15
            missing.append("exact_line_anchor")
        else:
            missing.append("code_anchor")

        # 3. Callers & Dependents Mapped (+0.20)
        if cross_file_links:
            score.callers_score = 0.20
        elif len(candidate_files) == 1 and declarations:
            # Single self-contained module where declaration has no external callers detected
            score.callers_score = 0.20
        else:
            missing.append("callers_and_breaking_changes")
            score.callers_score = 0.05

        # 4. Configs & Env Bindings (+0.20)
        # Check if code references env vars
        code_references_env = False
        for decl in declarations:
            body = decl.signature + " " + (decl.docstring or "")
            if any(
                k in body
                for k in (
                    "os.environ",
                    "os.getenv",
                    "process.env",
                    "config",
                    "settings",
                )
            ):
                code_references_env = True
                break

        if not code_references_env:
            # Code does not depend on env vars -> fully satisfied
            score.config_score = 0.20
        else:
            if discovered_env_vars or found_config_files:
                score.config_score = 0.20
            else:
                missing.append("env_var_or_config_bindings")
                score.config_score = 0.05

        score.missing_aspects = missing
        score.calculate_total(threshold)
        return score


@dataclass
class ReconHopTrace:
    hop_number: int
    intent: GoalIntent
    sub_query: str
    discovered_files: list[str] = field(default_factory=list)
    new_declarations_count: int = 0
    current_sufficiency: float = 0.0


@dataclass
class ReconReport:
    query: str
    decomposed: DecomposedGoal
    final_score: SufficiencyScore
    candidate_files: list[str] = field(default_factory=list)
    declarations: list[DeclarationUnit] = field(default_factory=list)
    relationship_report: RelationshipReport | None = field(default=None)
    env_vars: set[str] = field(default_factory=set)
    config_files: list[str] = field(default_factory=list)
    hops: list[ReconHopTrace] = field(default_factory=list)
    is_budget_exhausted: bool = False


class MultiHopReconEngine:
    """
    Coordinates multi-hop traversal (up to 6 hops) until Context Sufficiency >= 0.80
    or navigation budget is exhausted.
    """

    MAX_HOPS = 6

    def __init__(
        self, workspace_root: Path, config: ProjectConfig | None = None
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.config = config or load_config(start_dir=self.workspace_root)

    def run(
        self,
        query: str,
        hierarchical_explorer: Any,
        max_hops: int | None = None,
        threshold: float = 0.80,
    ) -> ReconReport:
        effective_max_hops = min(max_hops or self.MAX_HOPS, self.MAX_HOPS)
        decomposed = GoalDecomposer.decompose(query)

        visited_symbols: set[str] = set()
        visited_files: set[str] = set()
        accumulated_declarations: list[DeclarationUnit] = []
        accumulated_files: list[str] = []
        discovered_env_vars: set[str] = set()
        discovered_config_files: list[str] = []
        cross_file_links: list[str] = []
        hops_trace: list[ReconHopTrace] = []

        is_budget_exhausted = False
        current_sub_query = query
        relationship_report: RelationshipReport | None = None

        for hop_idx in range(1, effective_max_hops + 1):
            # 1. Execute Search / Traversal for current sub_query
            candidates, is_incomplete = hierarchical_explorer.explore(current_sub_query)
            if is_incomplete:
                is_budget_exhausted = True

            new_files = [f for f in candidates if f not in visited_files]
            visited_files.update(new_files)
            accumulated_files.extend(new_files)

            # 2. Extract Declarations from new candidates
            hop_new_decls = 0
            for file_path in new_files:
                full_path = self.workspace_root / file_path
                if not full_path.is_file():
                    continue

                # Check if config file
                name_lower = full_path.name.lower()
                if (
                    any(
                        ext in name_lower
                        for ext in (
                            ".env",
                            ".toml",
                            ".yaml",
                            ".yml",
                            ".json",
                            "settings",
                        )
                    )
                    and file_path not in discovered_config_files
                ):
                    discovered_config_files.append(file_path)

                try:
                    content = full_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                # Look for env vars in content
                for ev in re.findall(r"\b[A-Z][A-Z0-9_]{3,}\b", content):
                    if ev not in (
                        "HTTP",
                        "JSON",
                        "REST",
                        "POST",
                        "GET",
                        "TRUE",
                        "FALSE",
                    ):
                        discovered_env_vars.add(ev)

                # Parse declarations for code files
                if any(
                    file_path.endswith(ext)
                    for ext in (".py", ".ts", ".js", ".go", ".rs")
                ):
                    units = DeclarationParser.parse(content, file_path=file_path)
                    for u in units:
                        if u.name not in visited_symbols:
                            visited_symbols.add(u.name)
                            accumulated_declarations.append(u)
                            hop_new_decls += 1

            # 3. Relationship pass across all accumulated declarations
            if accumulated_declarations:
                query_tokens = decomposed.primary_symbols or [decomposed.original_query]
                relationship_report = RelationshipLinker.trace_relationships(
                    declarations=accumulated_declarations,
                    all_candidate_files=accumulated_files,
                    query_tokens=query_tokens,
                )
                cross_file_links = [
                    f"{link.caller_unit} ({link.source_file}) -> {link.target_symbol} ({link.target_file})"
                    for link in relationship_report.links
                ]

            # 4. Evaluate Context Sufficiency
            score = ContextSufficiencyEvaluator.evaluate(
                decomposed=decomposed,
                candidate_files=accumulated_files,
                declarations=accumulated_declarations,
                cross_file_links=cross_file_links,
                discovered_env_vars=discovered_env_vars,
                found_config_files=discovered_config_files,
                threshold=threshold,
            )

            # Record Hop Trace
            hops_trace.append(
                ReconHopTrace(
                    hop_number=hop_idx,
                    intent=decomposed.intent,
                    sub_query=current_sub_query,
                    discovered_files=new_files,
                    new_declarations_count=hop_new_decls,
                    current_sufficiency=score.total_score,
                )
            )

            # Check termination
            if score.is_sufficient or is_budget_exhausted:
                break

            # 5. Hybrid Dynamic Query Refinement for next hop
            current_sub_query = self._generate_next_query(
                decomposed=decomposed,
                score=score,
                declarations=accumulated_declarations,
                discovered_env_vars=discovered_env_vars,
                visited_symbols=visited_symbols,
                accumulated_files=accumulated_files,
            )

        return ReconReport(
            query=query,
            decomposed=decomposed,
            final_score=score,
            candidate_files=accumulated_files,
            declarations=accumulated_declarations,
            relationship_report=relationship_report,
            env_vars=discovered_env_vars,
            config_files=discovered_config_files,
            hops=hops_trace,
            is_budget_exhausted=is_budget_exhausted,
        )

    def _generate_next_query(
        self,
        decomposed: DecomposedGoal,
        score: SufficiencyScore,
        declarations: list[DeclarationUnit],
        discovered_env_vars: set[str],
        visited_symbols: set[str],
        accumulated_files: list[str] | None = None,
    ) -> str:
        """
        Hybrid Dynamic Query Refinement: queries MidFlightAnalyst (Qwen 3B)
        and falls back to deterministic rule-based refinement.
        """
        # Try local Mid-Flight Analyst first
        try:
            from .mid_flight import MidFlightAnalyst

            analyst = MidFlightAnalyst(timeout=4)
            suggested = analyst.suggest_next_hop_query(
                query=decomposed.original_query,
                missing_aspects=score.missing_aspects,
                examined_files=accumulated_files or [],
                discovered_symbols=list(visited_symbols)[:8],
            )
            if suggested:
                return suggested
        except (OSError, ValueError, RuntimeError) as exc:
            logger.debug("Mid-flight query generation skipped: %s", exc)

        # If missing mounting point in scaffold
        if "mounting_point" in score.missing_aspects:
            return "router urls routes __init__ index entrypoint"

        # If missing exemplar in scaffold
        if "exemplar_donor_template" in score.missing_aspects and score.mounting_point:
            parent_dir = str(Path(score.mounting_point).parent)
            return f"service handler controller in {parent_dir}"

        # If missing callers
        if "callers_and_breaking_changes" in score.missing_aspects and declarations:
            # Pick primary declaration name
            primary_decl = declarations[0]
            return f"caller call reference {primary_decl.name}"

        # If missing env var bindings
        if (
            "env_var_or_config_bindings" in score.missing_aspects
            and discovered_env_vars
        ):
            target_env = min(discovered_env_vars)
            return f"{target_env} env config settings"

        # Fallback to secondary symbols or original query tokens
        remaining_symbols = [
            s for s in decomposed.primary_symbols if s not in visited_symbols
        ]
        if remaining_symbols:
            return " ".join(remaining_symbols)

        return decomposed.original_query
