from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import generate_default_config_toml, load_config
from .core.benchmark import format_benchmark_table, run_matrix_benchmark
from .core.learning import FeedbackLearner
from .core.router import LayaDecisionRouter
from .executor import Investigator
from .inventory import scan_inventory
from .schemas import DecisionRequest, InvestigationFeedback, TaskCategory
from .server.mcp import run_mcp_server
from .skill import get_skill_markdown, install_skill

MAX_ROUNDS = 5


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="codeprobe",
        description="codeprobe: Universal Decision Router and Policy Engine for AI Coding Agents",
    )

    subparsers = parser.add_subparsers(dest="command")

    # Command: init
    init_parser = subparsers.add_parser(
        "init", help="Initialize starter .codeprobe/rules.toml in current repository"
    )
    init_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Overwrite existing configuration file",
    )

    # Command: config
    config_parser = subparsers.add_parser(
        "config", help="Display active project configuration and discovered path"
    )
    config_parser.add_argument(
        "--json", action="store_true", help="Output configuration as JSON"
    )

    # Command: serve
    serve_parser = subparsers.add_parser(
        "serve", help="Start codeprobe MCP or REST server"
    )
    serve_parser.add_argument(
        "--sse", action="store_true", help="Run MCP server with SSE transport"
    )
    serve_parser.add_argument(
        "--http", action="store_true", help="Run HTTP REST server (FastAPI)"
    )
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address for SSE/HTTP (default: 127.0.0.1)",
    )
    serve_parser.add_argument(
        "--port", type=int, default=8000, help="Port for SSE/HTTP (default: 8000)"
    )

    # Command: route
    route_parser = subparsers.add_parser(
        "route", help="Evaluate a coding goal and return decision JSON"
    )
    route_parser.add_argument("goal", nargs="+", help="Goal or user request")

    # Command: test-matrix
    bench_parser = subparsers.add_parser(
        "test-matrix", help="Run benchmark suite against all decision matrices"
    )
    bench_parser.add_argument(
        "--category",
        choices=[c.value for c in TaskCategory],
        help="Filter benchmark by category",
    )
    bench_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed failure assertions"
    )

    # Command: feedback
    fb_parser = subparsers.add_parser(
        "feedback",
        help="Submit evaluation to self-train and calibrate CodeProbe weights",
    )
    fb_parser.add_argument(
        "investigation_id", help="Investigation ID (e.g. inv_1728123456_a1b2c3d4)"
    )
    fb_parser.add_argument(
        "--score",
        "-s",
        type=int,
        required=True,
        choices=[1, 2, 3, 4, 5],
        help="Rating score from 1 (poor) to 5 (excellent)",
    )
    fb_parser.add_argument(
        "--text", "-t", default=None, help="Feedback description or correction notes"
    )
    fb_parser.add_argument(
        "--helpful", "-H", nargs="*", default=None, help="List of helpful file paths"
    )
    fb_parser.add_argument(
        "--unhelpful",
        "-U",
        nargs="*",
        default=None,
        help="List of noisy or irrelevant file paths",
    )

    # Command: files (pre-flight inventory)
    files_parser = subparsers.add_parser(
        "files", help="Pre-flight workspace inventory and byte volume breakdown"
    )
    files_parser.add_argument(
        "root", nargs="?", default=".", help="Root path to inventory (default: .)"
    )
    files_parser.add_argument(
        "--exclude",
        "-e",
        action="append",
        default=[],
        help="Exclude pattern (can specify multiple)",
    )
    files_parser.add_argument(
        "--json", action="store_true", help="Output inventory as JSON"
    )

    # Command: llm-server
    llm_parser = subparsers.add_parser(
        "llm-server", help="Manage background local llama-server daemon"
    )
    llm_parser.add_argument(
        "action",
        choices=["start", "stop", "status", "restart"],
        help="Action to perform on local llama-server",
    )
    llm_parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    llm_parser.add_argument("--port", type=int, default=8033, help="Port (default: 8033)")
    llm_parser.add_argument("--gpu-layers", type=int, default=None, help="GPU layers to offload")

    # Command: skill
    skill_parser = subparsers.add_parser(
        "skill", help="Install or print CodeProbe agent skill (SKILL.md)"
    )
    skill_parser.add_argument(
        "--global",
        "-g",
        dest="is_global",
        action="store_true",
        help="Install skill globally for user profile (~/.gemini/config, ~/.claude, etc.)",
    )
    skill_parser.add_argument(
        "--print",
        "-p",
        action="store_true",
        help="Print SKILL.md contents to stdout without saving",
    )
    skill_parser.add_argument(
        "--dest", "-d", default=None, help="Custom target directory for installation"
    )

    # Command: apply
    apply_parser = subparsers.add_parser(
        "apply", help="Safely apply ready-to-code patch from investigation"
    )
    apply_parser.add_argument(
        "--file", "-f", default=None, help="Specific file to patch or rollback"
    )
    apply_parser.add_argument(
        "--rollback", action="store_true", help="Rollback changes from backup file (.bak)"
    )
    apply_parser.add_argument(
        "--dry-run", action="store_true", help="Display diff without modifying files"
    )

    # Command: investigate (legacy)
    inv_parser = subparsers.add_parser(
        "investigate", help="Run iterative investigation loop"
    )
    inv_parser.add_argument("request", nargs="+", help="Investigation query")
    inv_parser.add_argument(
        "--mode",
        "-m",
        choices=["auto", "code", "compare", "survey"],
        default="auto",
        help="Investigation mode override: auto, code, compare, survey",
    )

    # Default fallback arguments if no subcommand is given
    parser.add_argument(
        "default_request",
        nargs="*",
        help="Direct request (runs investigate by default)",
    )
    parser.add_argument(
        "--mode",
        "-m",
        choices=["auto", "code", "compare", "survey"],
        default="auto",
        help="Investigation mode override: auto, code, compare, survey",
    )

    args = parser.parse_args()

    if args.command == "init":
        target_dir = Path.cwd() / ".codeprobe"
        target_file = target_dir / "rules.toml"

        if target_file.exists() and not args.force:
            print(
                f"Configuration file already exists at {target_file}. Use --force to overwrite."
            )
            sys.exit(1)

        target_dir.mkdir(parents=True, exist_ok=True)
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(generate_default_config_toml())

        print(f"Successfully initialized codeprobe rules at: {target_file}")
        return

    if args.command == "config":
        cfg = load_config()
        if args.json:
            print(cfg.model_dump_json(indent=2))
        else:
            print(
                f"Discovered Config: {cfg.config_path or 'Default In-Memory (No file found)'}"
            )
            print("\nActive Configuration:")
            print(f"  Forbidden Files  : {cfg.guardrails.forbidden_files}")
            print(f"  Read-Only Files  : {cfg.guardrails.read_only_files}")
            print(f"  Require Tests    : {cfg.policy.require_tests_before_edit}")
            print(f"  Blast Radius Max : {cfg.policy.blast_radius_limit}")
            print(f"  Max Slice Lines  : {cfg.policy.max_file_slice_lines}")
            print(f"  Navigation Budget: {cfg.policy.navigation_budget_bytes} bytes")
            print(f"  Default Threshold: {cfg.thresholds.default}")
        return

    if args.command == "files":
        root_path = Path(args.root).resolve()
        inv = scan_inventory(root_path, exclude_patterns=args.exclude)
        if args.json:
            print(json.dumps(inv.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(inv.format_human_summary())
        return

    if args.command == "serve":
        if args.http:
            try:
                from .server.http import run_http_server
            except ImportError:
                print(
                    "❌ Error: HTTP server requires 'fastapi' and 'uvicorn'.\n"
                    "Install them with: pip install 'codeprobe[http]' or uv pip install fastapi uvicorn",
                    file=sys.stderr,
                )
                sys.exit(1)
            run_http_server(host=args.host, port=args.port)
        elif args.sse:
            run_mcp_server(transport="sse", host=args.host, port=args.port)
        else:
            run_mcp_server(transport="stdio")
        return

    if args.command == "route":
        goal_text = " ".join(args.goal)
        router = LayaDecisionRouter()
        req = DecisionRequest(user_goal=goal_text)
        decision = router.route(req)
        print(decision.model_dump_json(indent=2))
        return

    if args.command == "test-matrix":
        cat_filter = TaskCategory(args.category) if args.category else None
        results = run_matrix_benchmark(category_filter=cat_filter)
        print(format_benchmark_table(results))

        if args.verbose:
            failed_results = [r for r in results if not r.passed]
            if failed_results:
                print("\nFailure Details:")
                for r in failed_results:
                    print(f"  - {r.scenario_name}: {r.details}")

        all_passed = all(r.passed for r in results)
        sys.exit(0 if all_passed else 1)

    if args.command == "feedback":
        fb = InvestigationFeedback(
            investigation_id=args.investigation_id,
            score=args.score,
            feedback_text=args.text,
            helpful_files=args.helpful,
            unhelpful_files=args.unhelpful,
        )
        resp = FeedbackLearner.process_feedback(fb)
        print(f"✅ {resp.message}")
        return

    if args.command == "skill":
        if args.print:
            print(get_skill_markdown())
            return
        dest_p = Path(args.dest).resolve() if args.dest else None
        results = install_skill(
            workspace_root=Path.cwd(), dest_path=dest_p, is_global=args.is_global
        )
        if not results:
            print("⚠️ No suitable skill installation directory detected.")
            sys.exit(1)
        for skill_file, success in results:
            if success:
                print(f"✅ Successfully installed CodeProbe skill at: {skill_file}")
            else:
                print(f"❌ Failed to write skill to: {skill_file}")
        return

    if args.command == "llm-server":
        from .core.llm_server import (
            get_server_status,
            start_server_daemon,
            stop_server_daemon,
        )

        if args.action == "start":
            res = start_server_daemon(host=args.host, port=args.port, gpu_layers=args.gpu_layers)
            print(f"🚀 llama-server: {res.get('status')} | URL: http://{res.get('host')}:{res.get('port')}")
            if "pid" in res:
                print(f"   PID: {res['pid']} | Model: {res.get('model')}")
                print(f"   Logs: {res.get('log_file')}")
            return
        elif args.action == "stop":
            res = stop_server_daemon()
            print(f"🛑 llama-server: {res.get('status')} (PID: {res.get('pid')})")
            return
        elif args.action == "restart":
            stop_server_daemon()
            res = start_server_daemon(host=args.host, port=args.port, gpu_layers=args.gpu_layers)
            print(f"🔄 llama-server restarted: {res.get('status')} | PID: {res.get('pid')}")
            return
        elif args.action == "status":
            stat = get_server_status(host=args.host, port=args.port)
            status_emoji = "🟢 ALIVE" if stat["alive"] else "🔴 STOPPED"
            print(f"\nllama-server status: {status_emoji}")
            print(f"  Endpoint: http://{stat['host']}:{stat['port']}")
            print(f"  PID:      {stat['pid']}")
            print(f"  Binary:   {stat['binary']}")
            print(f"  Model:    {stat['model']}")
            print(f"  Log File: {stat['log_file']}\n")
            return

    if args.command == "apply":
        from .core.patcher import PatchApplicator

        applicator = PatchApplicator(Path.cwd())

        if args.rollback:
            if not args.file:
                print("❌ Please specify --file <path> to rollback.")
                sys.exit(1)
            res = applicator.rollback(args.file)
            if res.success:
                print(f"✅ Successfully rolled back: {args.file}")
            else:
                print(f"❌ Rollback failed: {res.error_message}")
            return

        last_file = Path.cwd() / ".codeprobe" / "last_investigation.json"
        if not last_file.is_file():
            print("⚠️ No previous investigation found (.codeprobe/last_investigation.json). Run `codeprobe investigate` first.")
            sys.exit(1)

        try:
            data = json.loads(last_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"❌ Failed to parse last investigation: {e}")
            sys.exit(1)

        ready = data.get("ready_to_code")
        if not ready or not ready.get("targets"):
            print("⚠️ Last investigation did not produce any ready-to-code targets.")
            return

        from .schemas import CodeTarget

        targets = [CodeTarget.model_validate(t) for t in ready["targets"]]
        target_to_apply = targets[0]
        if args.file:
            matched = [t for t in targets if t.file_path == args.file]
            if matched:
                target_to_apply = matched[0]

        print(f"\n🔧 Patching target: {target_to_apply.file_path} (lines {target_to_apply.start_line}-{target_to_apply.end_line})")
        patch_res = applicator.apply_target(target_to_apply, dry_run=args.dry_run)
        if patch_res.success:
            if args.dry_run:
                print("📋 Dry-Run Diff Preview:\n")
                print(patch_res.diff)
            else:
                print(f"✅ Successfully patched: {patch_res.file_path}")
                if patch_res.backup_path:
                    print(f"📦 Backup created at: {patch_res.backup_path}")
        else:
            print(f"❌ Patch failed: {patch_res.error_message}")
        return

    # If investigate subcommand or positional fallback
    req_parts = getattr(args, "request", None) or args.default_request
    if not req_parts:
        parser.print_help()
        sys.exit(1)

    user_request = " ".join(req_parts)
    investigator = Investigator()

    print(f"\n🔍 CodeProbe Autonomous Investigation: '{user_request}'")
    print("=" * 70)

    mode_arg = getattr(args, "mode", "auto")
    result = investigator.explore(
        query=user_request,
        max_steps=5,
        synthesize_summary=True,
        mode=mode_arg,
    )

    if result.needs_clarification:
        print(f"\n{result.summary}")
        if sys.stdin.isatty():
            try:
                clarified = input("\n👉 Enter component, symbol, or clarification [Enter to exit]: ").strip()
                if clarified:
                    user_request = f"{user_request} ({clarified})"
                    print(f"\n🔄 Continuing with clarified query: '{user_request}'")
                    result = investigator.explore(
                        query=user_request,
                        max_steps=5,
                        synthesize_summary=True,
                        mode=mode_arg,
                    )
                else:
                    return
            except (KeyboardInterrupt, EOFError):
                return
        else:
            return

    print(
        f"\n📊 Strategy: {result.strategy} | Sufficiency: {result.sufficiency_score * 100:.1f}% | Hops: {result.hop_count} | Steps: {result.steps_executed}"
    )
    if result.mounting_point:
        print(f"🎯 Mounting Point: {result.mounting_point}")
    if result.exemplar_file:
        print(f"✨ Exemplar Donor: {result.exemplar_file}")
    if result.missing_aspects:
        print(f"⚠️  Missing Context: {', '.join(result.missing_aspects)}")

    print(f"📁 Examined Files ({len(result.examined_files)}):")
    for f in result.examined_files:
        print(f"   - {f}")

    if result.discovered_symbols:
        print(f"🧩 Discovered Symbols: {', '.join(result.discovered_symbols[:10])}")

    if result.cross_file_links:
        print(f"🔗 Cross-File Relationships ({len(result.cross_file_links)}):")
        for lk in result.cross_file_links[:5]:
            print(f"   - {lk}")

    if result.retracted_files:
        print(f"🗑️  Retracted False Positives ({len(result.retracted_files)}):")
        for f in result.retracted_files[:5]:
            print(f"   - {f}")

    print("\n" + "=" * 70)
    print("📝 FINDINGS & SYNTHESIS:")
    print("=" * 70)
    print(result.summary)

    if result.ready_to_code and result.ready_to_code.targets:
        print("\n" + "=" * 70)
        print(f"🎯 READY-TO-CODE TARGETS ({len(result.ready_to_code.targets)}):")
        print("=" * 70)
        for i, target in enumerate(result.ready_to_code.targets, 1):
            print(
                f"\n[{i}] File: {target.file_path} (Lines {target.start_line}-{target.end_line}) | Role: {target.role}"
            )
            if target.diff_preview:
                print(f"{target.diff_preview}")
            else:
                print(f"Target Content:\n{target.target_content}")
                print(f"Replacement Content:\n{target.replacement_content}")

        if result.ready_to_code.blast_radius:
            print(f"\n⚠️  Blast Radius ({len(result.ready_to_code.blast_radius)}):")
            for caller in result.ready_to_code.blast_radius:
                print(f"   • {caller}")
