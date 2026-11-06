from __future__ import annotations

import ast
import difflib
import logging
from dataclasses import dataclass
from pathlib import Path

from ..schemas import CodeTarget

logger = logging.getLogger(__name__)


@dataclass
class PatchResult:
    success: bool
    file_path: str
    diff: str = ""
    error_message: str | None = None
    backup_path: str | None = None


class PatchApplicator:
    """
    Safely applies ReadyToCode payloads with AST syntax verification,
    automatic file backups, dry-run previews, and rollback protection.
    """

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()

    def validate_syntax(self, file_path: str, proposed_content: str) -> None:
        """
        Validate syntax before writing to disk.
        Raises ValueError if syntax error is detected.
        """
        p_low = file_path.lower()
        if p_low.endswith(".py"):
            try:
                ast.parse(proposed_content, filename=file_path)
            except SyntaxError as e:
                raise ValueError(f"Python syntax error at line {e.lineno}: {e.msg}") from e
        elif any(p_low.endswith(ext) for ext in (".ts", ".js", ".go", ".rs", ".json")):
            # Balanced bracket validation
            stack: list[str] = []
            pairs = {")": "(", "}": "{", "]": "["}
            for ch in proposed_content:
                if ch in "({[":
                    stack.append(ch)
                elif ch in ")}]":
                    if not stack or stack[-1] != pairs[ch]:
                        raise ValueError(f"Mismatched bracket '{ch}' detected in {file_path}")
                    stack.pop()
            if stack:
                raise ValueError(f"Unclosed bracket '{stack[-1]}' detected in {file_path}")

    def preview_target(self, target: CodeTarget) -> str:
        """Generate unified diff preview between current and target content."""
        orig_lines = target.current_code.splitlines(keepends=True)
        new_lines = target.replacement_content.splitlines(keepends=True)
        diff = difflib.unified_diff(
            orig_lines,
            new_lines,
            fromfile=f"a/{target.file_path}",
            tofile=f"b/{target.file_path}",
        )
        return "".join(diff)

    def apply_target(self, target: CodeTarget, dry_run: bool = False) -> PatchResult:
        full_path = self.workspace_root / target.file_path
        if not full_path.is_file():
            return PatchResult(
                success=False,
                file_path=target.file_path,
                error_message=f"Target file does not exist: {target.file_path}",
            )

        try:
            original_file_content = full_path.read_text(encoding="utf-8")
        except OSError as e:
            return PatchResult(
                success=False,
                file_path=target.file_path,
                error_message=f"Failed to read target file: {e}",
            )

        match_str = target.target_content or target.current_code
        if match_str not in original_file_content:
            return PatchResult(
                success=False,
                file_path=target.file_path,
                error_message="Target code snippet does not match file content (file may have changed).",
            )

        # Substitute code snippet
        new_file_content = original_file_content.replace(
            match_str, target.replacement_content, 1
        )

        # 1. Syntax check proposed content
        try:
            self.validate_syntax(target.file_path, new_file_content)
        except ValueError as exc:
            return PatchResult(
                success=False,
                file_path=target.file_path,
                error_message=f"Syntax validation rejected patch: {exc}",
            )

        diff = self.preview_target(target)
        if dry_run:
            return PatchResult(
                success=True,
                file_path=target.file_path,
                diff=diff,
            )

        # 2. Backup original file
        backup_path = full_path.with_suffix(full_path.suffix + ".bak")
        try:
            backup_path.write_text(original_file_content, encoding="utf-8")
        except OSError as e:
            return PatchResult(
                success=False,
                file_path=target.file_path,
                error_message=f"Failed to create backup at {backup_path}: {e}",
            )

        # 3. Write new file content
        try:
            full_path.write_text(new_file_content, encoding="utf-8")
        except OSError as e:
            # Revert from backup if write failed
            if backup_path.is_file():
                backup_path.rename(full_path)
            return PatchResult(
                success=False,
                file_path=target.file_path,
                error_message=f"Failed to write patch to {full_path}: {e}",
            )

        return PatchResult(
            success=True,
            file_path=target.file_path,
            diff=diff,
            backup_path=str(backup_path),
        )

    def rollback(self, file_path: str) -> PatchResult:
        full_path = self.workspace_root / file_path
        backup_path = full_path.with_suffix(full_path.suffix + ".bak")

        if not backup_path.is_file():
            return PatchResult(
                success=False,
                file_path=file_path,
                error_message=f"No backup file found at {backup_path}",
            )

        try:
            backup_content = backup_path.read_text(encoding="utf-8")
            full_path.write_text(backup_content, encoding="utf-8")
            backup_path.unlink()
            return PatchResult(success=True, file_path=file_path)
        except OSError as e:
            return PatchResult(
                success=False,
                file_path=file_path,
                error_message=f"Rollback failed: {e}",
            )
