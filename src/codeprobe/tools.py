import subprocess
from pathlib import Path

_ACTIVE_WORKSPACE_ROOT: Path | None = None


def set_workspace_root(path: Path | str | None) -> Path:
    global _ACTIVE_WORKSPACE_ROOT
    if path:
        p = Path(path).resolve()
        if p.is_file():
            p = p.parent
        _ACTIVE_WORKSPACE_ROOT = p
    else:
        _ACTIVE_WORKSPACE_ROOT = Path.cwd().resolve()
    return _ACTIVE_WORKSPACE_ROOT


def get_workspace_root() -> Path:
    global _ACTIVE_WORKSPACE_ROOT
    if _ACTIVE_WORKSPACE_ROOT is None:
        _ACTIVE_WORKSPACE_ROOT = Path.cwd().resolve()
    return _ACTIVE_WORKSPACE_ROOT


ROOT = get_workspace_root()
MAX_OUTPUT = 20_000
MAX_FILE_SIZE = 50_000


def _run(
    args: list[str],
    *,
    timeout: int = 30,
    workspace: Path | None = None,
) -> str:
    cwd_path = workspace or get_workspace_root()
    result = subprocess.run(
        args,
        cwd=cwd_path,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )

    output = result.stdout

    if result.stderr:
        output += f"\n[stderr]\n{result.stderr}"

    if result.returncode != 0:
        output += f"\n[exit code: {result.returncode}]"

    return output[:MAX_OUTPUT]


def search_code(
    query: str, path_filter: str | None = None, case_sensitive: bool = False
) -> str:
    """Search source code using ripgrep with robust pattern matching."""
    args = [
        "rg",
        "-n",
        "--hidden",
        "--glob",
        "!.git",
        "--glob",
        "!node_modules",
        "--glob",
        "!__pycache__",
        "--glob",
        "!.venv",
        "--glob",
        "!*.lock",
        "--glob",
        "!uv.lock",
        "--glob",
        "!package-lock.json",
        "--glob",
        "!yarn.lock",
        "--glob",
        "!pnpm-lock.yaml",
        "--glob",
        "!poetry.lock",
        "--glob",
        "!Cargo.lock",
        "--glob",
        "!bun.lock",
        "--glob",
        "!.codeprobe",
        "--glob",
        "!.gemini",
        "--glob",
        "!*.min.js",
        "--glob",
        "!*.map",
        "--glob",
        "!*.pyc",
    ]
    if not case_sensitive:
        args.append("-i")
    if path_filter:
        args.extend(["--glob", path_filter])
    args.extend([query, "."])
    return _run(args)


def read_file(path: str, max_chars: int = MAX_OUTPUT) -> str:
    """Read a repository file."""
    root = get_workspace_root()
    target = (root / path).resolve()

    if not target.is_relative_to(root):
        raise ValueError(f"Path outside repository: {path}")

    if not target.is_file():
        raise FileNotFoundError(path)

    if (target.stat().st_size) > MAX_FILE_SIZE:
        # Fallback to reading first chunk
        with target.open("r", encoding="utf-8", errors="replace") as f:
            return f.read(max_chars)

    return target.read_text(errors="replace")[:max_chars]


def read_file_slice(path: str, start_line: int = 1, end_line: int = 150) -> str:
    """Read a specific line range slice of a file."""
    root = get_workspace_root()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return ""
    try:
        lines = target.read_text(errors="replace").splitlines()
        start = max(1, start_line) - 1
        end = min(len(lines), end_line)
        slice_lines = lines[start:end]
        numbered = [f"{i + start + 1}: {line}" for i, line in enumerate(slice_lines)]
        return "\n".join(numbered)
    except OSError as exc:
        return f"[Error slicing file: {exc}]"


def list_files(pattern: str = "*") -> str:
    """List files in the repository."""
    root = get_workspace_root()
    files = []

    for path in root.rglob(pattern):
        if not path.is_file():
            continue

        if (
            ".git" in path.parts
            or ".codeprobe" in path.parts
            or ".gemini" in path.parts
        ):
            continue

        if "node_modules" in path.parts:
            continue

        if "__pycache__" in path.parts:
            continue

        if path.name.endswith(".lock") or path.name.endswith(".lockb"):
            continue

        files.append(str(path.relative_to(root)))

    return "\n".join(sorted(files)[:5000])


def git_status() -> str:
    return _run(["git", "status", "--short"])


def git_diff() -> str:
    return _run(["git", "diff", "--", "."])


def git_log(query: str = "") -> str:
    args = [
        "git",
        "log",
        "--oneline",
        "--decorate",
        "-20",
    ]

    if query:
        args.extend(["--grep", query])

    return _run(args)


def run_tests() -> str:
    """
    Auto-detect and run tests across Rust (cargo), TypeScript/JavaScript (bun/npm/yarn/pnpm),
    Go (go test), and Python (pytest/uv).
    """
    root = get_workspace_root()

    # 1. Rust (Cargo)
    if (root / "Cargo.toml").exists():
        return _run(["cargo", "test", "--", "-q"], timeout=300)

    # 2. Go (go.mod)
    if (root / "go.mod").exists():
        return _run(["go", "test", "./..."], timeout=300)

    # 3. TypeScript / JavaScript (Node, Bun, PNPM, Yarn, NPM)
    if (root / "package.json").exists():
        if (root / "bun.lock" or root / "bun.lockb").exists():
            return _run(["bun", "test"], timeout=300)
        elif (root / "pnpm-lock.yaml").exists():
            return _run(["pnpm", "test"], timeout=300)
        elif (root / "yarn.lock").exists():
            return _run(["yarn", "test"], timeout=300)
        else:
            return _run(["npm", "test", "--", "--run"], timeout=300)

    # 4. Python (pytest, uv)
    if (
        (root / "pytest.ini").exists()
        or (root / "pyproject.toml").exists()
        or (root / "pytest").exists()
        or (root / "tests").exists()
    ):
        return _run(["uv", "run", "pytest", "-q"], timeout=300)

    return "No supported test suite configuration detected (Rust, TypeScript/JS, Go, Python)"
