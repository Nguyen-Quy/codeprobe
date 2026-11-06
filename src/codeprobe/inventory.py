from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import load_config

logger = logging.getLogger(__name__)

DEFAULT_IGNORED_DIRS: set[str] = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "target",
    ".idea",
    ".vscode",
    ".turbo",
    ".next",
    ".cache",
    ".codeprobe/cache",
}

DEFAULT_BINARY_EXTENSIONS: set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".webp",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".wasm",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".rar",
    ".pdf",
    ".doc",
    ".docx",
    ".pyc",
    ".pyo",
    ".pyd",
    ".class",
    ".jar",
    ".db",
    ".sqlite",
    ".sqlite3",
}

LANGUAGE_EXTENSION_MAP: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".js": "JavaScript",
    ".jsx": "JavaScript (React)",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".c": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".cs": "C#",
    ".php": "PHP",
    ".rb": "Ruby",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".scala": "Scala",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".json": "JSON",
    ".toml": "TOML",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".md": "Markdown",
    ".sh": "Shell",
    ".bash": "Shell",
    ".sql": "SQL",
}


@dataclass
class DirStats:
    files: int = 0
    bytes: int = 0
    languages: dict[str, int] = field(default_factory=dict)


@dataclass
class WorkspaceInventory:
    scanned_root: str
    total_files: int
    total_bytes: int
    breakdown_by_dir: dict[str, DirStats]
    language_distribution: dict[str, int]
    file_extensions: dict[str, int]
    excluded_files_count: int

    def format_human_summary(self) -> str:
        lines = [
            f"📁 Workspace Inventory for: {self.scanned_root}",
            f"   Total Files: {self.total_files:,} | Total Code Volume: {self.format_bytes(self.total_bytes)}",
            f"   Excluded Files: {self.excluded_files_count:,}",
            "",
            "📊 Directory Breakdown (Top-level):",
        ]
        sorted_dirs = sorted(
            self.breakdown_by_dir.items(), key=lambda kv: kv[1].bytes, reverse=True
        )
        for dname, stats in sorted_dirs:
            lang_summary = ", ".join(
                f"{lang}: {cnt}"
                for lang, cnt in sorted(
                    stats.languages.items(), key=lambda x: x[1], reverse=True
                )[:3]
            )
            lines.append(
                f"   • {dname + '/':<25} {stats.files:>4} files ({self.format_bytes(stats.bytes):>9})  [{lang_summary}]"
            )

        lines.append("")
        lines.append("🔤 Primary Languages:")
        sorted_langs = sorted(
            self.language_distribution.items(), key=lambda kv: kv[1], reverse=True
        )
        for lang, count in sorted_langs[:8]:
            pct = (count / self.total_files * 100) if self.total_files > 0 else 0
            lines.append(f"   • {lang:<20} {count:>4} files ({pct:>5.1f}%)")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned_root": self.scanned_root,
            "total_files": self.total_files,
            "total_bytes": self.total_bytes,
            "formatted_bytes": self.format_bytes(self.total_bytes),
            "excluded_files_count": self.excluded_files_count,
            "breakdown_by_dir": {
                k: {
                    "files": v.files,
                    "bytes": v.bytes,
                    "formatted_bytes": self.format_bytes(v.bytes),
                    "languages": v.languages,
                }
                for k, v in self.breakdown_by_dir.items()
            },
            "language_distribution": self.language_distribution,
            "file_extensions": self.file_extensions,
        }

    @staticmethod
    def format_bytes(num_bytes: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if num_bytes < 1024.0:
                return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{num_bytes} B"
            num_bytes /= 1024.0
        return f"{num_bytes:.1f} TB"


def _read_gitignore_patterns(root_dir: Path) -> list[str]:
    patterns: list[str] = []
    gitignore_file = root_dir / ".gitignore"
    if gitignore_file.is_file():
        try:
            with open(gitignore_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    s = line.strip()
                    if s and not s.startswith("#"):
                        patterns.append(s)
        except OSError as exc:
            logger.debug("Failed to read .gitignore at %s: %s", gitignore_file, exc)
    return patterns


def scan_inventory(
    root_dir: Path | None = None,
    exclude_patterns: list[str] | None = None,
) -> WorkspaceInventory:
    """
    Fast pre-flight discovery of workspace files and sizes without reading source or using tokens.
    """
    root = (root_dir or Path.cwd()).resolve()
    exclude_list = list(exclude_patterns or [])

    # Load project guardrails config for forbidden patterns
    config = load_config(root)
    forbidden_patterns = list(config.guardrails.forbidden_files)
    gitignore_patterns = _read_gitignore_patterns(root)

    all_excludes = exclude_list + forbidden_patterns + gitignore_patterns

    total_files = 0
    total_bytes = 0
    excluded_count = 0
    breakdown: dict[str, DirStats] = {}
    lang_dist: dict[str, int] = {}
    ext_dist: dict[str, int] = {}

    for path in root.rglob("*"):
        # Check if any parent dir is in DEFAULT_IGNORED_DIRS
        rel_parts = path.relative_to(root).parts
        if any(part in DEFAULT_IGNORED_DIRS for part in rel_parts):
            excluded_count += 1
            continue

        if not path.is_file():
            continue

        rel_path = str(path.relative_to(root))
        ext = path.suffix.lower()

        # Check binary files
        if ext in DEFAULT_BINARY_EXTENSIONS:
            excluded_count += 1
            continue

        # Check excludes against patterns
        is_excluded = False
        for pat in all_excludes:
            clean_pat = pat.rstrip("/")
            if (
                fnmatch.fnmatch(rel_path, clean_pat)
                or fnmatch.fnmatch(path.name, clean_pat)
                or fnmatch.fnmatch(f"*/{path.name}", clean_pat)
            ):
                is_excluded = True
                break

        if is_excluded:
            excluded_count += 1
            continue

        # Valid code / project file
        try:
            size = path.stat().st_size
        except OSError:
            size = 0

        total_files += 1
        total_bytes += size

        # Top-level directory group
        top_dir = rel_parts[0] if len(rel_parts) > 1 else "(root)"
        if top_dir not in breakdown:
            breakdown[top_dir] = DirStats()
        breakdown[top_dir].files += 1
        breakdown[top_dir].bytes += size

        # Language identification
        lang = LANGUAGE_EXTENSION_MAP.get(ext, f"Other ({ext})" if ext else "Plaintext")
        breakdown[top_dir].languages[lang] = (
            breakdown[top_dir].languages.get(lang, 0) + 1
        )
        lang_dist[lang] = lang_dist.get(lang, 0) + 1
        ext_dist[ext] = ext_dist.get(ext, 0) + 1

    return WorkspaceInventory(
        scanned_root=str(root),
        total_files=total_files,
        total_bytes=total_bytes,
        breakdown_by_dir=breakdown,
        language_distribution=lang_dist,
        file_extensions=ext_dist,
        excluded_files_count=excluded_count,
    )
