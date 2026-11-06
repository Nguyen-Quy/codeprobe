from __future__ import annotations

import ast
import re
from pathlib import Path

from ..schemas import DeclarationUnit
from .infra import (
    DockerComposeParser,
    DockerfileParser,
    K8sManifestParser,
    ShellEnvResolver,
)

__all__ = [
    "GENERIC_ENV_BLACKLIST",
    "NOISE_FUNCTION_BLACKLIST",
    "DeclarationParser",
    "DeclarationUnit",
]

NOISE_FUNCTION_BLACKLIST: frozenset[str] = frozenset(
    {
        "usage",
        "help",
        "show_help",
        "print_help",
        "display_help",
        "check_kubectl",
        "check_cmd",
        "check_env",
        "check_prerequisites",
        "echo_info",
        "log_info",
        "print_error",
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
        "$1",
        "$2",
        "$3",
        "$@",
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


class DeclarationParser:
    """
    Multi-language structural declaration parser (Python, TS/JS, Go, Rust, Infra) with caller tracking.
    """

    @classmethod
    def is_infra_file(cls, file_path: str) -> bool:
        """Checks whether a file path points to an infrastructure or configuration manifest."""
        p = Path(file_path)
        name = p.name.lower()
        ext = p.suffix.lower()

        if ext in (".yaml", ".yml"):
            return True
        if name in (
            "dockerfile",
            "dockerfile.dev",
            "dockerfile.prod",
        ) or name.startswith("dockerfile."):
            return True
        if ext in (".sh", ".bash", ".zsh"):
            return True
        return bool(name == ".env" or name.startswith(".env."))

    @classmethod
    def parse_infra(cls, content: str, file_path: str = "") -> list[DeclarationUnit]:
        """
        Parses infrastructure manifests (Kubernetes, Docker Compose, Dockerfile, Shell, .env)
        into standard DeclarationUnits.
        """
        ext = Path(file_path).suffix.lower() if file_path else ""

        # 1. Dockerfile
        if DockerfileParser.is_dockerfile(file_path):
            return DockerfileParser.parse(content, file_path)

        # 2. Docker Compose
        if DockerComposeParser.is_compose_file(file_path):
            return DockerComposeParser.parse(content, file_path)

        # 3. Shell scripts (.sh, .bash)
        if ShellEnvResolver.is_shell_file(file_path):
            return ShellEnvResolver.parse_shell_script(content, file_path)

        # 4. Environment files (.env, .env.*)
        if ShellEnvResolver.is_env_file(file_path):
            return ShellEnvResolver.parse_env_file(content, file_path)

        # 5. YAML files -> Check if Kubernetes manifest first, otherwise check Compose
        if ext in (".yaml", ".yml"):
            k8s_units = K8sManifestParser.parse(content, file_path)
            if k8s_units:
                return k8s_units
            compose_units = DockerComposeParser.parse(content, file_path)
            if compose_units:
                return compose_units

        return []

    @classmethod
    def parse(cls, content: str, file_path: str = "") -> list[DeclarationUnit]:
        ext = Path(file_path).suffix.lower() if file_path else ""

        # Check infrastructure & configuration manifests (Kubernetes, Docker, Shell, .env)
        if cls.is_infra_file(file_path):
            infra_units = cls.parse_infra(content, file_path)
            if infra_units:
                return infra_units

        if ext in (".py", ".pyi"):
            return cls.parse_python(content, file_path)
        elif ext in (".ts", ".tsx", ".js", ".jsx"):
            return cls.parse_javascript_typescript(content, file_path)
        elif ext == ".go":
            return cls.parse_go(content, file_path)
        elif ext == ".rs":
            return cls.parse_rust(content, file_path)
        else:
            return cls.parse_fallback(content, file_path)

    @classmethod
    def parse_python(cls, content: str, file_path: str = "") -> list[DeclarationUnit]:
        units: list[DeclarationUnit] = []
        lines = content.splitlines()

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return cls.parse_fallback(content, file_path)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = node.lineno
                end = getattr(node, "end_lineno", start + len(node.body))
                kind = "class" if isinstance(node, ast.ClassDef) else "function"

                # Extract docstring
                docstring = ast.get_docstring(node)

                # Extract signature line
                sig_line = (
                    lines[start - 1].strip() if 0 < start <= len(lines) else node.name
                )

                # Extract calls inside this unit
                calls: set[str] = set()
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        if isinstance(sub.func, ast.Name):
                            calls.add(sub.func.id)
                        elif isinstance(sub.func, ast.Attribute):
                            calls.add(sub.func.attr)
                            # e.g. os.environ.get("VAR") or os.getenv("VAR")
                            if sub.func.attr in ("get", "getenv") and sub.args:
                                first_arg = sub.args[0]
                                if (
                                    isinstance(first_arg, ast.Constant)
                                    and isinstance(first_arg.value, str)
                                    and re.match(r"^[A-Z][A-Z0-9_]{2,}$", first_arg.value)
                                ):
                                    calls.add(first_arg.value)
                    elif (
                        isinstance(sub, ast.Subscript)
                        and isinstance(sub.slice, ast.Constant)
                        and isinstance(sub.slice.value, str)
                        and re.match(r"^[A-Z][A-Z0-9_]{2,}$", sub.slice.value)
                    ):
                        calls.add(sub.slice.value)

                # Bounded body snippet
                snippet_lines = lines[start - 1 : min(end, start + 8)]
                snippet = "\n".join(f"    {ln}" for ln in snippet_lines)

                units.append(
                    DeclarationUnit(
                        name=node.name,
                        kind=kind,
                        file_path=file_path,
                        start_line=start,
                        end_line=end,
                        signature=sig_line,
                        docstring=docstring,
                        body_snippet=snippet,
                        calls=sorted(calls)[:10],
                    )
                )

        return units

    @classmethod
    def parse_javascript_typescript(
        cls, content: str, file_path: str = ""
    ) -> list[DeclarationUnit]:
        units: list[DeclarationUnit] = []
        lines = content.splitlines()

        pattern = re.compile(
            r"^\s*(?:export\s+)?(?:async\s+)?(?:function\s+([a-zA-Z0-9_$]+)|class\s+([a-zA-Z0-9_$]+)|interface\s+([a-zA-Z0-9_$]+)|const\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>)"
        )

        for i, line in enumerate(lines, 1):
            m = pattern.search(line)
            if m:
                name = (
                    m.group(1) or m.group(2) or m.group(3) or m.group(4) or "anonymous"
                )
                kind = (
                    "class"
                    if "class " in line
                    else ("interface" if "interface " in line else "function")
                )
                start = i
                end = min(len(lines), start + 12)

                snippet_lines = lines[start - 1 : end]
                snippet = "\n".join(f"    {ln}" for ln in snippet_lines[:6])
                snippet_text = "\n".join(snippet_lines)

                # Extract call tokens inside snippet
                call_tokens = re.findall(r"([a-zA-Z0-9_$]+)\(", snippet_text)
                calls = [
                    c
                    for c in call_tokens
                    if c not in {name, "if", "for", "while", "switch", "catch"}
                ]

                # Extract env vars like process.env.VAR or process.env["VAR"]
                for env_m in re.finditer(
                    r"process\.env(?:\.([A-Za-z0-9_]+)|\[['\"]([A-Za-z0-9_]+)['\"]\])",
                    snippet_text,
                ):
                    env_k = env_m.group(1) or env_m.group(2)
                    if env_k:
                        calls.append(env_k)

                units.append(
                    DeclarationUnit(
                        name=name,
                        kind=kind,
                        file_path=file_path,
                        start_line=start,
                        end_line=end,
                        signature=line.strip(),
                        docstring=None,
                        body_snippet=snippet,
                        calls=sorted(set(calls))[:8],
                    )
                )

        return units

    @classmethod
    def parse_go(cls, content: str, file_path: str = "") -> list[DeclarationUnit]:
        units: list[DeclarationUnit] = []
        lines = content.splitlines()

        pattern = re.compile(
            r"^\s*func\s+(?:\([^)]+\)\s+)?([a-zA-Z0-9_]+)\s*\(|^\s*type\s+([a-zA-Z0-9_]+)\s+(?:struct|interface)"
        )

        for i, line in enumerate(lines, 1):
            m = pattern.search(line)
            if m:
                name = m.group(1) or m.group(2) or "unknown"
                kind = (
                    "struct"
                    if "struct" in line
                    else ("interface" if "interface" in line else "function")
                )
                start = i
                end = min(len(lines), start + 15)

                snippet_lines = lines[start - 1 : min(len(lines), start + 6)]
                snippet = "\n".join(f"    {ln}" for ln in snippet_lines)

                call_tokens = re.findall(
                    r"([a-zA-Z0-9_]+)\(", "\n".join(lines[start - 1 : end])
                )
                calls = [
                    c
                    for c in call_tokens
                    if c not in {name, "if", "for", "make", "new", "len", "append"}
                ]

                units.append(
                    DeclarationUnit(
                        name=name,
                        kind=kind,
                        file_path=file_path,
                        start_line=start,
                        end_line=end,
                        signature=line.strip(),
                        body_snippet=snippet,
                        calls=sorted(set(calls))[:8],
                    )
                )

        return units

    @classmethod
    def parse_rust(cls, content: str, file_path: str = "") -> list[DeclarationUnit]:
        units: list[DeclarationUnit] = []
        lines = content.splitlines()

        pattern = re.compile(
            r"^\s*(?:pub(?:\([^\)]+\))?\s+)?(?:fn|struct|trait|enum|impl)\s+([a-zA-Z0-9_]+)"
        )

        for i, line in enumerate(lines, 1):
            m = pattern.search(line)
            if m:
                name = m.group(1)
                kind = (
                    "struct"
                    if "struct " in line
                    else (
                        "trait"
                        if "trait " in line
                        else ("impl" if "impl " in line else "function")
                    )
                )
                start = i
                end = min(len(lines), start + 15)

                snippet_lines = lines[start - 1 : min(len(lines), start + 6)]
                snippet = "\n".join(f"    {ln}" for ln in snippet_lines)

                call_tokens = re.findall(
                    r"([a-zA-Z0-9_]+)(?:::|\()", "\n".join(lines[start - 1 : end])
                )
                calls = [
                    c
                    for c in call_tokens
                    if c not in {name, "if", "match", "let", "Some", "Ok"}
                ]

                units.append(
                    DeclarationUnit(
                        name=name,
                        kind=kind,
                        file_path=file_path,
                        start_line=start,
                        end_line=end,
                        signature=line.strip(),
                        body_snippet=snippet,
                        calls=sorted(set(calls))[:8],
                    )
                )

        return units

    @classmethod
    def parse_fallback(cls, content: str, file_path: str = "") -> list[DeclarationUnit]:
        lines = content.splitlines()
        if not lines:
            return []

        snippet = "\n".join(f"    {ln}" for ln in lines[:8])
        return [
            DeclarationUnit(
                name=Path(file_path).stem if file_path else "content",
                kind="file",
                file_path=file_path,
                start_line=1,
                end_line=len(lines),
                signature=lines[0][:80] if lines else "",
                body_snippet=snippet,
                calls=[],
            )
        ]
