from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .config import load_config
from .core.router import LayaDecisionRouter
from .extractor import QueryKeywordExtractor
from .inventory import (
    DEFAULT_BINARY_EXTENSIONS,
    DEFAULT_IGNORED_DIRS,
    _read_gitignore_patterns,
)

logger = logging.getLogger(__name__)


@dataclass
class NavigationBudget:
    max_bytes: int = 250_000  # Default 250 KB budget for navigation previews
    consumed_bytes: int = 0
    is_incomplete: bool = False

    def can_consume(self, byte_count: int) -> bool:
        if self.consumed_bytes + byte_count > self.max_bytes:
            self.is_incomplete = True
            return False
        return True

    def consume(self, byte_count: int) -> bool:
        if not self.can_consume(byte_count):
            self.consumed_bytes += byte_count
            self.is_incomplete = True
            return False
        self.consumed_bytes += byte_count
        return True


@dataclass
class DirectorySample:
    path: Path
    relative_path: str
    file_count: int
    sample_files: list[str]
    relevance_score: float = 0.0


class HierarchicalExplorer:
    """
    Hierarchical directory traversal with progressive branch pruning and byte budgeting.
    """

    def __init__(
        self,
        workspace_root: Path,
        router: LayaDecisionRouter | None = None,
        budget: NavigationBudget | None = None,
    ):
        self.workspace_root = workspace_root.resolve()
        self.router = router or LayaDecisionRouter()
        self.config = load_config(self.workspace_root)
        self.budget = budget or NavigationBudget(
            max_bytes=self.config.policy.navigation_budget_bytes
        )
        self.gitignore_patterns = _read_gitignore_patterns(self.workspace_root)

    def is_path_ignored(self, path: Path) -> bool:
        rel_parts = path.relative_to(self.workspace_root).parts
        return any(part in DEFAULT_IGNORED_DIRS for part in rel_parts)

    def sample_directory(
        self, dir_path: Path, max_samples: int = 10
    ) -> DirectorySample | None:
        if not dir_path.is_dir() or self.is_path_ignored(dir_path):
            return None

        rel_dir = str(dir_path.relative_to(self.workspace_root))
        files: list[str] = []
        file_count = 0

        try:
            for item in dir_path.iterdir():
                if item.is_file():
                    ext = item.suffix.lower()
                    if (
                        ext not in DEFAULT_BINARY_EXTENSIONS
                        and not item.name.startswith(".")
                    ):
                        file_count += 1
                        if len(files) < max_samples:
                            files.append(item.name)
        except OSError:
            return None

        return DirectorySample(
            path=dir_path,
            relative_path=rel_dir if rel_dir != "." else "(root)",
            file_count=file_count,
            sample_files=files,
        )

    def score_branch_relevance(
        self, sample: DirectorySample, query_tokens: list[str]
    ) -> float:
        """
        Calculate branch relevance score based on dir name, file samples, and query tokens.
        """
        score = 0.1  # base baseline
        dir_lower = sample.relative_path.lower()

        # Direct token match in directory name
        for tok in query_tokens:
            tok_l = tok.lower()
            if tok_l in dir_lower:
                score += 0.45
            for fname in sample.sample_files:
                if tok_l in fname.lower():
                    score += 0.35

        # Structural priority boosts
        if any(core in dir_lower for core in ["src", "lib", "core", "pkg", "app"]):
            score += 0.15
        elif any(sup in dir_lower for sup in ["tests", "test", "spec"]):
            if any(t in query_tokens for t in ["test", "testing", "spec", "verify"]):
                score += 0.40
            else:
                score += 0.05
        elif any(doc in dir_lower for doc in ["docs", "doc", ".planning"]):
            if any(
                t in query_tokens for t in ["plan", "doc", "spec", "roadmap", "phase"]
            ):
                score += 0.50
            else:
                score -= 0.10

        return min(1.0, max(0.0, score))

    def explore(
        self,
        query: str,
        max_candidate_files: int = 25,
        prune_threshold: float = 0.25,
    ) -> tuple[list[str], bool]:
        """
        Perform hierarchical traversal, returning ranked candidate files and budget completion status.
        """
        query_tokens = QueryKeywordExtractor.extract_search_tokens(query)
        candidates: list[tuple[str, float]] = []

        # 1. Inspect top-level branches
        top_dirs = [
            p
            for p in self.workspace_root.iterdir()
            if p.is_dir() and not self.is_path_ignored(p)
        ]
        branch_samples: list[DirectorySample] = []

        for d in top_dirs:
            s = self.sample_directory(d)
            if s:
                s.relevance_score = self.score_branch_relevance(s, query_tokens)
                branch_samples.append(s)

        # 2. Also sample root files
        root_sample = self.sample_directory(self.workspace_root)
        if root_sample:
            for rf in root_sample.sample_files:
                # Add root file candidate
                rf_path = self.workspace_root / rf
                try:
                    fsize = rf_path.stat().st_size
                except OSError:
                    fsize = 0
                if self.budget.consume(min(fsize, 4096)):
                    candidates.append((rf, 0.4))

        # 3. Sort branches by relevance and prune low-confidence branches
        branch_samples.sort(key=lambda x: x.relevance_score, reverse=True)

        for branch in branch_samples:
            if branch.relevance_score < prune_threshold:
                logger.debug(
                    f"Pruning branch {branch.relative_path} (score {branch.relevance_score:.2f} < {prune_threshold})"
                )
                continue

            if not self.budget.can_consume(1024):
                break

            # Explore qualifying branch files and immediate subdirectories
            try:
                for file_path in branch.path.rglob("*"):
                    if not file_path.is_file() or self.is_path_ignored(file_path):
                        continue
                    if file_path.suffix.lower() in DEFAULT_BINARY_EXTENSIONS:
                        continue

                    rel_f = str(file_path.relative_to(self.workspace_root))
                    try:
                        fsize = file_path.stat().st_size
                    except OSError:
                        fsize = 0

                    # Consume navigation preview byte budget
                    preview_bytes = min(fsize, 4096)
                    if not self.budget.consume(preview_bytes):
                        break

                    # Score file
                    f_score = branch.relevance_score
                    f_name_lower = file_path.name.lower()
                    for tok in query_tokens:
                        if tok.lower() in f_name_lower:
                            f_score += 0.35

                    candidates.append((rel_f, f_score))

                    if len(candidates) >= max_candidate_files * 2:
                        break
            except OSError:
                continue

            if self.budget.is_incomplete:
                break

        # Sort and deduplicate candidate files
        candidates.sort(key=lambda x: x[1], reverse=True)
        unique_files: list[str] = []
        seen: set[str] = set()
        for f, _ in candidates:
            if f not in seen:
                seen.add(f)
                unique_files.append(f)
            if len(unique_files) >= max_candidate_files:
                break

        return unique_files, self.budget.is_incomplete
