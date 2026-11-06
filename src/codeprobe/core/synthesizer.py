from __future__ import annotations

import difflib
import logging
import re
from pathlib import Path
from typing import ClassVar

from ..schemas import (
    CodeTarget,
    ComparisonMatrixPayload,
    ComparisonTarget,
    DecisionRequest,
    InvestigationMode,
    ReadyToCodePayload,
)
from ..tools import get_workspace_root
from .declarations import GENERIC_ENV_BLACKLIST, DeclarationUnit
from .infra import StructuralYamlSynthesizer
from .recon import ReconReport, classify_investigation_mode
from .relationships import RelationshipReport

logger = logging.getLogger(__name__)


class StateSynthesizer:
    """
    Compresses verbose agent state and evidence into dense,
    information-rich signal blocks for the Laya Router.
    """

    MAX_EVIDENCE_LINES = 80
    MAX_ERROR_LENGTH = 1000

    @classmethod
    def extract_file_paths(cls, text: str) -> list[str]:
        """Extract relative file paths from ripgrep output or logs."""
        paths: set[str] = set()
        for line in text.splitlines():
            match = re.match(
                r"^(?:\./)?([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)(?::\d+)?", line.strip()
            )
            if match:
                path = match.group(1)
                if not any(
                    excluded in path
                    for excluded in [".git", "node_modules", "__pycache__", ".venv"]
                ):
                    paths.add(path)
        return sorted(paths)

    @classmethod
    def synthesize_prompt(cls, request: DecisionRequest) -> str:
        """
        Synthesize the state into a structured prompt for Laya Router.
        """
        parts = [
            f"GOAL: {request.user_goal}",
            f"CURRENT STEP: {request.current_step} (Budget left: {request.budget_remaining_steps})",
        ]

        if request.task_category:
            parts.append(f"TASK CATEGORY: {request.task_category.value}")

        if request.active_file:
            parts.append(f"ACTIVE FILE: {request.active_file}")

        if request.last_error:
            truncated_error = request.last_error.strip()[: cls.MAX_ERROR_LENGTH]
            parts.append(f"LAST ERROR / EXCEPTION:\n{truncated_error}")

        all_known_files = set(request.known_files)
        if request.modified_files:
            parts.append(
                f"MODIFIED FILES IN WORKSPACE: {', '.join(request.modified_files)}"
            )

        # Process evidence snippets
        if request.collected_evidence:
            evidence_text = "\n".join(request.collected_evidence)
            extracted_paths = cls.extract_file_paths(evidence_text)
            all_known_files.update(extracted_paths)

            evidence_lines = evidence_text.splitlines()
            if len(evidence_lines) > cls.MAX_EVIDENCE_LINES:
                evidence_lines = evidence_lines[-cls.MAX_EVIDENCE_LINES :]

            condensed_evidence = "\n".join(evidence_lines)
            parts.append(f"COLLECTED EVIDENCE (Condensed):\n{condensed_evidence}")
        else:
            parts.append("COLLECTED EVIDENCE: (None gathered yet)")

        if all_known_files:
            parts.append(
                f"CANDIDATE DISCOVERED FILES: {', '.join(sorted(all_known_files)[:15])}"
            )

        parts.append(
            "\nEvaluate the current state against the decision questions and output probability scores."
        )
        return "\n\n".join(parts)


class ReadyToCodeSynthesizer:
    """
    Deterministic synthesizer that produces concrete CodeTarget entries and
    ReadyToCodePayload without calling any external LLMs.
    """

    @classmethod
    def _generate_diff(cls, file_path: str, old_content: str, new_content: str) -> str:
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff_lines = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
            )
        )
        if not diff_lines:
            return ""
        diff_text = "".join(diff_lines)
        if not diff_text.endswith("\n"):
            diff_text += "\n"
        return f"```diff\n{diff_text}```"

    @classmethod
    def _build_target_from_declaration(
        cls,
        decl: DeclarationUnit,
        role: str,
        query: str,
        workspace_root: Path,
    ) -> CodeTarget | None:
        p = (
            workspace_root / decl.file_path
            if not Path(decl.file_path).is_absolute()
            else Path(decl.file_path)
        )
        current_code = ""
        start_line = max(1, decl.start_line)
        end_line = max(start_line, decl.end_line)

        if p.exists() and p.is_file():
            try:
                raw_lines = p.read_text(encoding="utf-8", errors="replace").splitlines(
                    keepends=True
                )
                total_lines = len(raw_lines)
                if total_lines > 0:
                    start_idx = min(start_line - 1, total_lines - 1)
                    end_idx = min(end_line, total_lines)
                    current_code = "".join(raw_lines[start_idx:end_idx])
            except OSError as exc:
                logger.debug("Could not read lines for %s: %s", decl.file_path, exc)

        if not current_code:
            current_code = decl.body_snippet or f"{decl.signature}\n"

        target_content = current_code
        # Strictly Zero Fake Diffs: do not inject fake comment directives
        replacement_content = current_code
        diff_preview = ""

        return CodeTarget(
            file_path=decl.file_path,
            role=role,
            start_line=start_line,
            end_line=end_line,
            current_code=current_code,
            target_content=target_content,
            replacement_content=replacement_content,
            diff_preview=diff_preview,
        )

    @classmethod
    def _build_env_target(
        cls,
        file_path: str,
        abs_path: Path,
        env_vars: set[str],
        tokens: set[str],
    ) -> CodeTarget | None:
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines(keepends=True)
        except OSError:
            return None

        # Look for existing matching env var line
        target_idx = -1
        for i, line in enumerate(lines):
            for ev in env_vars:
                if line.startswith((f"{ev}=", f"export {ev}=")):
                    target_idx = i
                    break
            if target_idx >= 0:
                break

        if target_idx >= 0:
            target_content = lines[target_idx]
            start_l = target_idx + 1
            end_l = start_l
            replacement_content = target_content
            if not replacement_content.endswith("\n"):
                replacement_content += "\n"
        else:
            # Append variable to .env
            var_name = next(iter(env_vars)) if env_vars else "CONFIG_KEY"
            target_content = lines[-1] if lines else "\n"
            start_l = max(1, len(lines))
            end_l = start_l
            replacement_content = target_content
            if not replacement_content.endswith("\n"):
                replacement_content += "\n"
            replacement_content += f"{var_name}=default_value\n"

        diff = cls._generate_diff(file_path, target_content, replacement_content)
        return CodeTarget(
            file_path=file_path,
            role="config_binding",
            start_line=start_l,
            end_line=end_l,
            current_code=target_content,
            target_content=target_content,
            replacement_content=replacement_content,
            diff_preview=diff,
        )

    @classmethod
    def _build_compose_target(
        cls,
        file_path: str,
        abs_path: Path,
        env_vars: set[str],
        tokens: set[str],
    ) -> CodeTarget | None:
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines(keepends=True)
        except OSError:
            return None

        # Filter out generic blacklist tokens and ensure business relevance
        valid_env_vars = {
            ev
            for ev in env_vars
            if ev not in GENERIC_ENV_BLACKLIST and len(ev) >= 4 and ev.isupper()
        }
        if not valid_env_vars:
            # Strictly zero fake diffs: do not inject dummy service configs or fake comments
            return None

        # Locate environment or services block
        target_idx = -1
        for i, line in enumerate(lines):
            if "environment:" in line or "services:" in line:
                target_idx = i
                break

        if target_idx < 0:
            return None

        # Anchor a slice of 3 lines
        start_idx = max(0, target_idx)
        end_idx = min(len(lines), start_idx + 3)
        target_content = "".join(lines[start_idx:end_idx]) if lines else "services:\n"
        start_l = start_idx + 1
        end_l = max(start_l, end_idx)

        replacement_content = target_content
        if not replacement_content.endswith("\n"):
            replacement_content += "\n"

        ev = next(iter(valid_env_vars))
        replacement_content += f"      - {ev}=${{{ev}}}\n"

        diff = cls._generate_diff(file_path, target_content, replacement_content)
        return CodeTarget(
            file_path=file_path,
            role="infra_manifest",
            start_line=start_l,
            end_line=end_l,
            current_code=target_content,
            target_content=target_content,
            replacement_content=replacement_content,
            diff_preview=diff,
        )

    @classmethod
    def _build_k8s_target(
        cls,
        file_path: str,
        abs_path: Path,
        env_vars: set[str],
        tokens: set[str],
    ) -> CodeTarget | None:
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        # 1. Check if Kustomization manifest
        if StructuralYamlSynthesizer.is_kustomization(file_path, content):
            res = StructuralYamlSynthesizer.synthesize_kustomize_resource_target(
                file_path=file_path, content=content
            )
            if res:
                start_l, end_l, target_content, replacement_content = res
                diff = cls._generate_diff(
                    file_path, target_content, replacement_content
                )
                return CodeTarget(
                    file_path=file_path,
                    role="infra_manifest",
                    start_line=start_l,
                    end_line=end_l,
                    current_code=target_content,
                    target_content=target_content,
                    replacement_content=replacement_content,
                    diff_preview=diff,
                )

        valid_env_vars = {
            ev
            for ev in env_vars
            if ev not in GENERIC_ENV_BLACKLIST and len(ev) >= 4 and ev.isupper()
        }
        if not valid_env_vars:
            return None

        ev = next(iter(valid_env_vars))

        # 2. Check if Kubernetes manifest (CronJob, Deployment, StatefulSet, Pod)
        if StructuralYamlSynthesizer.is_k8s_manifest(content):
            res = StructuralYamlSynthesizer.synthesize_k8s_env_target(
                file_path=file_path, content=content, env_var_name=ev
            )
            if res:
                start_l, end_l, target_content, replacement_content = res
                diff = cls._generate_diff(
                    file_path, target_content, replacement_content
                )
                return CodeTarget(
                    file_path=file_path,
                    role="infra_manifest",
                    start_line=start_l,
                    end_line=end_l,
                    current_code=target_content,
                    target_content=target_content,
                    replacement_content=replacement_content,
                    diff_preview=diff,
                )

        # Strictly Zero Fake Diffs: return None if not a valid structural anchor
        return None

    @classmethod
    def synthesize(
        cls,
        query: str,
        examined_files: list[str],
        declarations: list[DeclarationUnit],
        recon_report: ReconReport | None = None,
        relationship_report: RelationshipReport | None = None,
        workspace_root: Path | None = None,
        mode: InvestigationMode | str | None = None,
    ) -> ReadyToCodePayload | None:
        """
        Synthesizes a concrete ReadyToCodePayload with primary and secondary code targets,
        exact line ranges, drop-in replacement chunks, diff previews, and blast radius.
        Strictly enforces Zero Fake Diffs and returns None unless in CODE_MODIFICATION mode
        with high confidence (>= 0.80).
        """
        resolved_mode = (
            mode
            if isinstance(mode, InvestigationMode) and mode != InvestigationMode.AUTO
            else classify_investigation_mode(query, explicit_mode=mode)
        )
        if resolved_mode != InvestigationMode.CODE_MODIFICATION:
            return None

        confidence = 0.85
        if recon_report and recon_report.final_score:
            confidence = min(
                0.95, max(0.50, round(recon_report.final_score.total_score, 2))
            )
        if confidence < 0.80:
            return None

        root = workspace_root or get_workspace_root()
        if not declarations and not examined_files:
            return None

        tokens = set(re.findall(r"[A-Za-z0-9_]{3,}", query.lower()))
        targets: list[CodeTarget] = []
        visited_files: set[str] = set()

        # 1. Check for Scaffold intent (Mounting Point + Exemplar)
        if (
            recon_report
            and recon_report.decomposed
            and recon_report.decomposed.is_scaffold
        ):
            mounting_point = recon_report.final_score.mounting_point
            if mounting_point:
                mp_path = (
                    root / mounting_point
                    if not Path(mounting_point).is_absolute()
                    else Path(mounting_point)
                )
                if mp_path.exists() and mp_path.is_file():
                    content = mp_path.read_text(encoding="utf-8", errors="replace")
                    lines = content.splitlines(keepends=True)
                    anchor_lines = lines[-3:] if len(lines) >= 3 else lines
                    anchor_text = "".join(anchor_lines) if anchor_lines else "\n"
                    start_l = max(1, len(lines) - len(anchor_lines) + 1)
                    end_l = max(start_l, len(lines))

                    replacement = anchor_text
                    if not replacement.endswith("\n"):
                        replacement += "\n"
                    replacement += (
                        "\n# Ready-to-Code: Mount new scaffold module/route here\n"
                    )

                    diff = cls._generate_diff(mounting_point, anchor_text, replacement)
                    targets.append(
                        CodeTarget(
                            file_path=mounting_point,
                            role="mounting_point",
                            start_line=start_l,
                            end_line=end_l,
                            current_code=anchor_text,
                            target_content=anchor_text,
                            replacement_content=replacement,
                            diff_preview=diff,
                        )
                    )
                    visited_files.add(mounting_point)

        # 2. Identify Primary Source Code Target
        primary_decl: DeclarationUnit | None = None
        best_score = -1

        for decl in declarations:
            score = 0
            d_name_lower = decl.name.lower()
            d_file_lower = decl.file_path.lower()

            for tok in tokens:
                if tok in d_name_lower:
                    score += 5
                if tok in d_file_lower:
                    score += 2
                if any(tok in c.lower() for c in decl.calls):
                    score += 3

            # Favor production code over tests
            if not any(t in d_file_lower for t in ["test", "mock", "fixture"]):
                score += 2

            if score > best_score:
                best_score = score
                primary_decl = decl

        if primary_decl and primary_decl.file_path not in visited_files:
            target = cls._build_target_from_declaration(
                primary_decl,
                role="primary_source",
                query=query,
                workspace_root=root,
            )
            if target:
                targets.append(target)
                visited_files.add(primary_decl.file_path)

        # 3. Identify Secondary Targets (Configurations, .env, Docker, K8s)
        env_vars_in_scope: set[str] = set()
        if recon_report and recon_report.env_vars:
            env_vars_in_scope.update(recon_report.env_vars)
        for decl in declarations:
            for call in decl.calls:
                if call.isupper() and len(call) >= 3:
                    env_vars_in_scope.add(call)

        for f in examined_files:
            if f in visited_files:
                continue
            f_lower = f.lower()
            p = root / f if not Path(f).is_absolute() else Path(f)
            if not p.exists() or not p.is_file():
                continue

            # A. .env file
            if p.name == ".env" or p.name.startswith(".env."):
                target = cls._build_env_target(f, p, env_vars_in_scope, tokens)
                if target:
                    targets.append(target)
                    visited_files.add(f)

            # B. docker-compose.yml
            elif "docker-compose" in f_lower or "compose.y" in f_lower:
                target = cls._build_compose_target(f, p, env_vars_in_scope, tokens)
                if target:
                    targets.append(target)
                    visited_files.add(f)

            # C. Kubernetes YAML manifests
            elif f_lower.endswith((".yaml", ".yml")) and any(
                k in f_lower for k in ["k8s", "deploy", "kube", "service"]
            ):
                target = cls._build_k8s_target(f, p, env_vars_in_scope, tokens)
                if target:
                    targets.append(target)
                    visited_files.add(f)

        if not targets and declarations:
            decl = declarations[0]
            target = cls._build_target_from_declaration(
                decl,
                role="primary_source",
                query=query,
                workspace_root=root,
            )
            if target:
                targets.append(target)

        if not targets:
            return None

        # 4. Compute Blast Radius (Deep Multi-Tier Propagation)
        blast_radius: list[str] = []
        primary_file = targets[0].file_path if targets else ""

        # Tier 1: Direct AST / symbol callers & donors
        if relationship_report:
            for lk in relationship_report.links:
                if lk.target_file == primary_file:
                    caller_str = f"{lk.caller_unit} ({lk.source_file})"
                    if caller_str not in blast_radius:
                        blast_radius.append(caller_str)
            for d in relationship_report.donor_files:
                if d != primary_file and d not in blast_radius:
                    blast_radius.append(f"dependency ({d})")

        # Tier 2 & 3: Cascading Infrastructure Impact (Scripts -> Generators -> Workloads)
        if primary_file and any(
            primary_file.endswith(ext) for ext in (".sh", ".bash", ".zsh", ".env")
        ):
            script_name = Path(primary_file).name
            script_stem = Path(primary_file).stem
            for f in examined_files:
                if f == primary_file:
                    continue
                f_p = root / f if not Path(f).is_absolute() else Path(f)
                if not f_p.exists() or not f_p.is_file():
                    continue
                try:
                    f_content = f_p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                if script_name in f_content or script_stem in f_content:
                    f_low = f.lower()
                    if "kustomiz" in f_low:
                        cascade_entry = f"kustomize_generator ({f} packs {script_name})"
                    elif any(
                        k in f_low
                        for k in (
                            "cronjob",
                            "deployment",
                            "statefulset",
                            "pod",
                            "daemonset",
                        )
                    ):
                        cascade_entry = f"k8s_workload ({f} executes {script_name})"
                    else:
                        cascade_entry = f"infra_dependent ({f})"

                    if cascade_entry not in blast_radius:
                        blast_radius.append(cascade_entry)

        # 5. Confidence
        confidence = 0.85
        if recon_report and recon_report.final_score:
            confidence = min(
                0.95, max(0.50, round(recon_report.final_score.total_score, 2))
            )

        summary_text = (
            f"Ready-to-code modification targets for '{query}'. "
            f"Prepared {len(targets)} concrete code/config target(s) with verbatim anchors."
        )

        return ReadyToCodePayload(
            summary=summary_text,
            targets=targets,
            blast_radius=blast_radius[:10],
            confidence=confidence,
        )


class ComparisonMatrixSynthesizer:
    """
    Deterministic comparison engine that produces structured ComparisonMatrixPayload
    for downstream agent consumption when mode is AUDIT_COMPARE.
    Detects paired subsystems across functional domains (deploy, backup, restore, dr, verify),
    inspects declaration units and files, and identifies missing capabilities and architectural gaps.
    """

    DOMAINS: ClassVar[list[str]] = ["deploy", "backup", "restore", "dr", "verify"]

    DOMAIN_KEYWORDS: ClassVar[dict[str, list[str]]] = {
        "deploy": ["deploy", "k8s", "kubernetes", "rollout", "release", "helm"],
        "backup": ["backup", "restic", "snapshot", "dump", "wal-g", "walg"],
        "restore": ["restore", "recover", "rollback", "pitr"],
        "dr": ["dr", "failover", "disaster", "switchover", "bizfly", "standby"],
        "verify": ["verify", "check", "health", "audit", "smoke", "validate"],
    }

    # Reference enterprise capabilities per domain
    DOMAIN_CAPABILITY_SIGNATURES: ClassVar[dict[str, list[tuple[str, list[str]]]]] = {
        "deploy": [
            ("image_build", ["build", "docker_build", "image", "kaniko"]),
            ("containerd_import", ["import", "containerd", "ctr", "k3s_import"]),
            ("migration_job_wait", ["migrate", "migration", "job_wait", "db_migrate"]),
            ("secret_sync", ["secret", "sealed_secret", "vault"]),
            ("smoke_test", ["smoke", "healthcheck", "curl", "probe"]),
        ],
        "backup": [
            ("full_retention_policy", ["forget", "prune", "retention", "keep_daily"]),
            ("dead_mans_snitch_heartbeat", ["snitch", "heartbeat", "dead_man", "ping"]),
            ("telegram_alert", ["telegram", "notify", "alert", "slack"]),
            ("lock_check_break", ["unlock", "break_lock", "check_lock"]),
            ("wal_g_streaming", ["wal_g", "wal-g", "pitr", "archive"]),
        ],
        "restore": [
            ("point_in_time_recovery", ["pitr", "target_time", "point_in_time"]),
            (
                "target_tenant_validation",
                ["validate_tenant", "check_tenant", "tenant_id"],
            ),
            (
                "service_quiesce",
                ["quiesce", "stop_service", "scale_zero", "maintenance_mode"],
            ),
        ],
        "dr": [
            ("dns_failover", ["dns", "cf_dns", "cloudflare", "bizfly_dns"]),
            ("standby_promotion", ["promote", "standby", "master_switch"]),
            ("replication_lag_check", ["lag", "replication", "sync_check"]),
        ],
        "verify": [
            ("ssl_expiry_check", ["ssl", "cert", "expiry", "tls"]),
            ("disk_threshold_probe", ["disk", "df", "storage", "threshold"]),
            ("database_connection_test", ["db_ping", "check_db", "test_connection"]),
        ],
    }

    @classmethod
    def _detect_subsystems(
        cls, examined_files: list[str], declarations: list[DeclarationUnit]
    ) -> list[str]:
        subsystems: list[str] = []
        all_paths = examined_files + [d.file_path for d in declarations]

        has_bash = any(
            p.endswith((".sh", ".bash"))
            or "/scripts/" in p
            or p.startswith("scripts/")
            or "backup/" in p
            for p in all_paths
        )
        has_rust = any(
            p.endswith(".rs") or "Cargo.toml" in p or "erp-cli" in p for p in all_paths
        )
        has_python = any(
            p.endswith(".py")
            and not any(test_k in p for test_k in ["test_", "/tests/"])
            for p in all_paths
        )
        has_go = any(p.endswith(".go") for p in all_paths)

        if has_bash:
            subsystems.append("bash_scripts")
        if has_rust:
            subsystems.append("rust_crate")
        if has_python and not (has_bash and has_rust):
            subsystems.append("python_backend")
        if has_go:
            subsystems.append("go_subsystem")

        if not subsystems:
            subsystems = ["source_scripts", "target_system"]
        elif len(subsystems) == 1:
            if "bash_scripts" in subsystems:
                subsystems.append("rust_crate")
            else:
                subsystems.append("target_subsystem")

        return subsystems

    @classmethod
    def _match_files_for_domain(
        cls, domain: str, all_files: list[str]
    ) -> tuple[list[str], list[str]]:
        """Separate candidate files into source (e.g. bash scripts) and target (e.g. rust crate) for a domain."""
        keywords = cls.DOMAIN_KEYWORDS.get(domain, [domain])
        source_candidates: list[str] = []
        target_candidates: list[str] = []

        for f in all_files:
            f_lower = f.lower()
            if not any(k in f_lower for k in keywords):
                continue
            if (
                f.endswith((".sh", ".bash"))
                or "scripts/" in f_lower
                or "backup/" in f_lower
            ):
                source_candidates.append(f)
            elif f.endswith(".rs") or "erp-cli" in f_lower or "tools/" in f_lower:
                target_candidates.append(f)
            else:
                if "legacy" in f_lower or "script" in f_lower:
                    source_candidates.append(f)
                else:
                    target_candidates.append(f)

        return source_candidates, target_candidates

    @classmethod
    def _inspect_capabilities(
        cls,
        domain: str,
        file_path: str,
        declarations: list[DeclarationUnit],
        workspace_root: Path | None,
    ) -> set[str]:
        """Detect capabilities present in a given file/component."""
        caps: set[str] = set()
        file_decls = [d for d in declarations if d.file_path == file_path]
        decl_text = " ".join(
            f"{d.name} {d.signature} {' '.join(d.calls)} {d.docstring or ''}"
            for d in file_decls
        ).lower()

        raw_text = ""
        if workspace_root:
            p = (
                workspace_root / file_path
                if not Path(file_path).is_absolute()
                else Path(file_path)
            )
            if p.exists() and p.is_file():
                try:
                    raw_text = p.read_text(encoding="utf-8", errors="replace").lower()
                except OSError:
                    pass

        combined_text = f"{decl_text} {raw_text}"
        signatures = cls.DOMAIN_CAPABILITY_SIGNATURES.get(domain, [])
        for cap_name, patterns in signatures:
            if any(pat in combined_text for pat in patterns):
                caps.add(cap_name)

        for d in file_decls:
            d_name_low = d.name.lower()
            if any(k in d_name_low for k in cls.DOMAIN_KEYWORDS.get(domain, [])):
                caps.add(d.name)

        return caps

    @classmethod
    def synthesize(
        cls,
        query: str,
        examined_files: list[str],
        declarations: list[DeclarationUnit],
        workspace_root: Path | None = None,
    ) -> ComparisonMatrixPayload:
        root = workspace_root or get_workspace_root()
        all_files = list(
            dict.fromkeys(examined_files + [d.file_path for d in declarations])
        )
        subsystems = cls._detect_subsystems(examined_files, declarations)

        component_pairs: list[ComparisonTarget] = []
        all_missing: list[str] = []

        for domain in cls.DOMAINS:
            source_files, target_files = cls._match_files_for_domain(domain, all_files)
            if not source_files and not target_files:
                continue

            src = source_files[0] if source_files else f"scripts/{domain}.sh (absent)"
            tgt = (
                target_files[0]
                if target_files
                else f"tools/erp-cli/src/{domain}.rs (absent)"
            )

            src_caps = (
                cls._inspect_capabilities(domain, src, declarations, root)
                if source_files
                else set()
            )
            tgt_caps = (
                cls._inspect_capabilities(domain, tgt, declarations, root)
                if target_files
                else set()
            )

            missing: list[str] = []
            if not target_files:
                parity_status = "MISSING_IN_TARGET"
                missing = [
                    f"Full {domain} subsystem implementation missing in target ({tgt})"
                ]
                if src_caps:
                    missing.extend(sorted(src_caps))
            else:
                if src_caps:
                    missing = sorted(src_caps - tgt_caps)
                else:
                    for cap_name, _ in cls.DOMAIN_CAPABILITY_SIGNATURES.get(domain, []):
                        if not any(c == cap_name for c in tgt_caps):
                            missing.append(cap_name)

                if not missing:
                    parity_status = "EQUIVALENT"
                elif len(missing) == len(src_caps) and src_caps:
                    parity_status = "MISSING_IN_TARGET"
                else:
                    parity_status = "PARTIAL"

            details = (
                f"Source ({src}) has {len(src_caps)} capability signals; "
                f"Target ({tgt}) has {len(tgt_caps)} capability signals. "
                f"Missing in target: {len(missing)}."
            )

            component_pairs.append(
                ComparisonTarget(
                    aspect=domain,
                    source_component=src,
                    target_component=tgt,
                    parity_status=parity_status,
                    missing_in_target=missing,
                    details=details,
                )
            )
            all_missing.extend(missing)

        # Architectural Gaps
        architectural_gaps: list[str] = []
        if any("wal_g" in m or "pitr" in m for m in all_missing) or not any(
            t.aspect == "backup" and t.parity_status == "EQUIVALENT"
            for t in component_pairs
        ):
            architectural_gaps.append(
                "Lacks WAL-G / PITR for database continuous streaming backup and point-in-time recovery"
            )
        if any(
            t.aspect == "dr" and t.parity_status != "EQUIVALENT"
            for t in component_pairs
        ):
            architectural_gaps.append(
                "Lacks automated DNS failover & standby promotion CLI workflow"
            )
        if any(
            t.aspect == "backup"
            and any("snitch" in m or "telegram" in m for m in t.missing_in_target)
            for t in component_pairs
        ):
            architectural_gaps.append(
                "Lacks Dead-Man's Snitch heartbeat pings and Telegram/Slack alert integrations"
            )
        if not any(
            "provision" in f.lower() or "tenant" in f.lower()
            for f in all_files
            if f.endswith(".rs")
        ):
            architectural_gaps.append(
                "Lacks dynamic tenant provisioning and database schema lifecycle CLI commands"
            )

        title = f"Subsystem Parity & Gap Comparison Matrix: {' vs '.join(subsystems)}"
        return ComparisonMatrixPayload(
            title=title,
            subsystems_detected=subsystems,
            component_pairs=component_pairs,
            architectural_gaps=architectural_gaps,
        )
