from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class LocalEvidenceCache:
    """
    Lightweight local cache for workspace inventories, previews, and declaration analysis.
    Stores JSON payloads under .codeprobe/cache/.
    """

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()
        self.cache_dir = self.workspace_root / ".codeprobe" / "cache"

    def _ensure_dir(self) -> bool:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            return True
        except OSError:
            return False

    @staticmethod
    def compute_key(namespace: str, *inputs: str) -> str:
        h = hashlib.sha256()
        h.update(namespace.encode("utf-8"))
        for item in inputs:
            h.update(b":")
            h.update(item.encode("utf-8"))
        return h.hexdigest()[:24]

    def get(self, namespace: str, *inputs: str) -> dict[str, Any] | None:
        key = self.compute_key(namespace, *inputs)
        cache_file = self.cache_dir / f"{namespace}_{key}.json"
        if not cache_file.is_file():
            return None
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except (OSError, json.JSONDecodeError, TypeError) as e:
            logger.debug("Cache read error for %s: %s", key, e)
            return None

    def set(self, namespace: str, data: dict[str, Any], *inputs: str) -> None:
        if not self._ensure_dir():
            return
        key = self.compute_key(namespace, *inputs)
        cache_file = self.cache_dir / f"{namespace}_{key}.json"
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except (OSError, TypeError, ValueError) as e:
            logger.debug("Cache write error for %s: %s", key, e)

    def clear(self) -> int:
        if not self.cache_dir.is_dir():
            return 0
        count = 0
        for f in self.cache_dir.glob("*.json"):
            try:
                f.unlink()
                count += 1
            except OSError:
                pass
        return count

    def get_git_head(self) -> str:
        """Fetch current git commit HEAD hash or 'unversioned'."""
        import subprocess

        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        return "unversioned"

    def get_investigation(self, query: str, mode: str) -> dict[str, Any] | None:
        commit_sha = self.get_git_head()
        return self.get("investigation", commit_sha, query, mode)

    def set_investigation(self, query: str, mode: str, data: dict[str, Any]) -> None:
        commit_sha = self.get_git_head()
        self.set("investigation", data, commit_sha, query, mode)
