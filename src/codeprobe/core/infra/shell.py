from __future__ import annotations

import logging
import re
from pathlib import Path

from ...schemas import DeclarationUnit

logger = logging.getLogger(__name__)

NOISE_FUNCTION_BLACKLIST: frozenset[str] = frozenset(
    {
        "usage",
        "help",
        "show_help",
        "print_help",
        "display_help",
        "check_kubectl",
        "check_cmd",
        "check_prerequisites",
        "echo_info",
        "log_info",
        "cleanup_temp",
        "print_usage",
        "usage_and_exit",
    }
)

GENERIC_ENV_BLACKLIST: frozenset[str] = frozenset(
    {
        "1",
        "2",
        "3",
        "TARGET",
        "ENVIRONMENT",
        "ENV",
        "KUBECONFIG",
        "PATH",
        "HOME",
        "USER",
        "ROOT_DIR",
        "SCRIPT_DIR",
        "BASH_SOURCE",
        "DIR",
        "PWD",
        "ARG",
        "TMP",
        "TEMP",
    }
)


class ShellEnvResolver:
    """
    Parses shell scripts (.sh, .bash) and environment files (.env, .env.*)
    into DeclarationUnits, extracting variable definitions (export FOO=bar),
    function declarations, and variable references ($FOO, ${FOO}).
    """

    @classmethod
    def is_env_file(cls, file_path: str) -> bool:
        name = Path(file_path).name.lower()
        return name == ".env" or name.startswith(".env.")

    @classmethod
    def is_shell_file(cls, file_path: str) -> bool:
        ext = Path(file_path).suffix.lower()
        return ext in (".sh", ".bash", ".zsh")

    @classmethod
    def parse_env_file(cls, content: str, file_path: str = "") -> list[DeclarationUnit]:
        lines = content.splitlines()
        defined_keys: list[str] = []
        units: list[DeclarationUnit] = []

        for idx, line in enumerate(lines, 1):
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue

            # Remove 'export ' prefix if present
            if clean.startswith("export "):
                clean = clean[7:].strip()

            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", clean)
            if m:
                key = m.group(1)
                val_snippet = m.group(2)[:30]
                defined_keys.append(key)

                if key.upper() not in GENERIC_ENV_BLACKLIST:
                    units.append(
                        DeclarationUnit(
                            name=key,
                            kind="env_var",
                            file_path=file_path,
                            start_line=idx,
                            end_line=idx,
                            signature=f"env {key}={val_snippet}...",
                            docstring=f"Environment variable defined in {file_path}",
                            calls=[],
                            body_snippet=line.strip(),
                        )
                    )

        # Also emit a summary unit for the whole .env file
        file_name = Path(file_path).name if file_path else ".env"
        units.append(
            DeclarationUnit(
                name=file_name,
                kind="env_file",
                file_path=file_path,
                start_line=1,
                end_line=len(lines) if lines else 1,
                signature=f"EnvFile {file_name} ({len(defined_keys)} variables)",
                docstring=f"Variables: {', '.join(defined_keys[:10])}",
                calls=defined_keys,
                body_snippet="\n".join(lines[:20]),
            )
        )

        return units

    @classmethod
    def parse_shell_script(
        cls, content: str, file_path: str = ""
    ) -> list[DeclarationUnit]:
        lines = content.splitlines()
        units: list[DeclarationUnit] = []

        exported_vars: list[str] = []
        referenced_vars: set[str] = set()
        function_starts: list[tuple[str, int]] = []
        cli_args: list[DeclarationUnit] = []
        trap_handlers: list[DeclarationUnit] = []

        for idx, line in enumerate(lines, 1):
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue

            # Check exports: export FOO=bar or export FOO
            m_exp = re.match(r"^export\s+([A-Za-z_][A-Za-z0-9_]*)(?:=.*)?$", clean)
            if m_exp:
                var_name = m_exp.group(1)
                exported_vars.append(var_name)
                if var_name.upper() not in GENERIC_ENV_BLACKLIST:
                    units.append(
                        DeclarationUnit(
                            name=var_name,
                            kind="env_var",
                            file_path=file_path,
                            start_line=idx,
                            end_line=idx,
                            signature=f"export {var_name}",
                            docstring=f"Shell export in {file_path}",
                            calls=[],
                            body_snippet=line.strip(),
                        )
                    )

            # Check CLI argument assignments: VAR="${1:-...}" or VAR="$1"
            m_arg = re.match(
                r"^([A-Za-z_][A-Za-z0-9_]*)=[\"']?\$\{?([1-9])(?::?[-=?+][^}\"']*)?\}?[\"']?$",
                clean,
            )
            if m_arg:
                arg_var = m_arg.group(1)
                arg_pos = m_arg.group(2)
                if arg_var.upper() not in GENERIC_ENV_BLACKLIST:
                    cli_args.append(
                        DeclarationUnit(
                            name=arg_var,
                            kind="argument",
                            file_path=file_path,
                            start_line=idx,
                            end_line=idx,
                            signature=clean,
                            docstring=f"CLI positional argument ${arg_pos} in {file_path}",
                            calls=[],
                            body_snippet=clean,
                        )
                    )

            # Check trap handlers: trap 'cleanup' EXIT or trap "handler" ERR EXIT
            m_trap = re.match(
                r"^trap\s+['\"]?([^'\"]+?)['\"]?\s+([A-Z0-9_\s]+)$", clean
            )
            if m_trap:
                handler_action = m_trap.group(1).strip()
                signals = m_trap.group(2).strip()
                primary_sig = signals.split()[0]
                # Extract calls from handler action
                calls = [
                    w
                    for w in re.findall(
                        r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", handler_action
                    )
                    if w not in ("exit", "echo", "true", "false", "return")
                ]
                trap_handlers.append(
                    DeclarationUnit(
                        name=f"trap_{primary_sig.lower()}",
                        kind="handler",
                        file_path=file_path,
                        start_line=idx,
                        end_line=idx,
                        signature=clean,
                        docstring=f"Shell trap handler for signal {signals}",
                        calls=calls,
                        body_snippet=clean,
                    )
                )

            # Check shell function definition:
            # 1) function name() {
            # 2) function name {
            # 3) name() {
            m_func = re.match(
                r"^(?:function\s+([A-Za-z0-9_\-]+)(?:\s*\(\))?|([A-Za-z0-9_\-]+)\s*\(\))\s*\{?",
                clean,
            )
            if m_func:
                f_name = m_func.group(1) or m_func.group(2)
                if (
                    f_name
                    and f_name.lower() not in NOISE_FUNCTION_BLACKLIST
                    and f_name
                    not in (
                        "if",
                        "then",
                        "else",
                        "elif",
                        "fi",
                        "for",
                        "while",
                        "do",
                        "done",
                        "case",
                        "esac",
                    )
                ):
                    function_starts.append((f_name, idx))

            # Check variable usages: $FOO or ${FOO}
            for m_ref in re.finditer(
                r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)(?::[-=?+].*)?\}|([A-Za-z_][A-Za-z0-9_]*))",
                line,
            ):
                ref = m_ref.group(1) or m_ref.group(2)
                if ref and ref not in (
                    "?",
                    "@",
                    "*",
                    "#",
                    "0",
                    "1",
                    "2",
                    "3",
                    "4",
                    "5",
                    "6",
                    "7",
                    "8",
                    "9",
                ):
                    referenced_vars.add(ref)

        # Append CLI argument units and trap handlers
        units.extend(cli_args)
        units.extend(trap_handlers)

        # Create units for functions with accurate block detection
        for i, (f_name, start_l) in enumerate(function_starts):
            # Locate closing brace '}' for this function
            end_l = start_l
            brace_depth = 0
            found_opening = False

            for l_idx in range(start_l, len(lines) + 1):
                cur_line = lines[l_idx - 1]
                # Count braces
                for char in cur_line:
                    if char == "{":
                        brace_depth += 1
                        found_opening = True
                    elif char == "}":
                        brace_depth -= 1
                        if found_opening and brace_depth <= 0:
                            end_l = l_idx
                            break
                if found_opening and brace_depth <= 0:
                    break

            if end_l == start_l:
                # Fallback: check next function start or single line
                end_l = (
                    function_starts[i + 1][1] - 1
                    if i + 1 < len(function_starts)
                    else min(start_l + 10, len(lines))
                )

            fn_lines = lines[start_l - 1 : end_l]
            fn_content = "\n".join(fn_lines)
            fn_refs = sorted(
                set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b", fn_content))
            )
            clean_calls = [r for r in fn_refs if r != f_name][:8]

            units.append(
                DeclarationUnit(
                    name=f_name,
                    kind="function",
                    file_path=file_path,
                    start_line=start_l,
                    end_line=end_l,
                    signature=f"function {f_name}()",
                    docstring=f"Shell function in {file_path}",
                    calls=clean_calls,
                    body_snippet="\n".join(fn_lines[:15]),
                )
            )

        # Top-level shell script unit
        file_name = Path(file_path).name if file_path else "script.sh"
        all_calls = sorted(set(exported_vars + list(referenced_vars)))
        units.append(
            DeclarationUnit(
                name=file_name,
                kind="shell_script",
                file_path=file_path,
                start_line=1,
                end_line=len(lines) if lines else 1,
                signature=f"ShellScript {file_name}",
                docstring=f"Exports: {', '.join(exported_vars[:6])} | Refs: {', '.join(list(referenced_vars)[:6])}",
                calls=all_calls,
                body_snippet="\n".join(lines[:20]),
            )
        )

        return units
