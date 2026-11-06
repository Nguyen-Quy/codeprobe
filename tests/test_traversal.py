from __future__ import annotations

from pathlib import Path

from codeprobe.traversal import HierarchicalExplorer, NavigationBudget


def test_navigation_budget_limits():
    budget = NavigationBudget(max_bytes=1000)

    # First consumption within budget
    assert budget.consume(500) is True
    assert budget.consumed_bytes == 500
    assert budget.is_incomplete is False

    # Second consumption exceeds budget
    assert budget.consume(600) is False
    assert budget.consumed_bytes == 1100
    assert budget.is_incomplete is True


def test_hierarchical_explorer_branch_pruning(tmp_path: Path):
    # Create relevant source branch
    auth_dir = tmp_path / "src" / "auth"
    auth_dir.mkdir(parents=True)
    (auth_dir / "service.py").write_text(
        "class AuthService:\n    def login(self): pass\n", encoding="utf-8"
    )
    (auth_dir / "tokens.py").write_text("def verify_jwt(): pass\n", encoding="utf-8")

    # Create irrelevant branch
    assets_dir = tmp_path / "assets" / "icons"
    assets_dir.mkdir(parents=True)
    (assets_dir / "logo.svg").write_text("<svg></svg>", encoding="utf-8")
    (assets_dir / "icon.txt").write_text("icon", encoding="utf-8")

    # Docs branch
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "guide.md").write_text("# User Guide", encoding="utf-8")

    budget = NavigationBudget(max_bytes=50_000)
    explorer = HierarchicalExplorer(tmp_path, budget=budget)

    # Search for authentication
    candidates, is_incomplete = explorer.explore(
        "Where is user auth and login handled?"
    )

    assert not is_incomplete
    # Should find auth files first and prune assets
    assert any("auth" in f for f in candidates)
    # Assets should not be prioritized
    assert not any("assets" in f for f in candidates)


def test_hierarchical_explorer_budget_exhaustion(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    for i in range(10):
        (src_dir / f"module_{i}.py").write_text("# code\n" * 500, encoding="utf-8")

    # Tiny budget of 500 bytes
    budget = NavigationBudget(max_bytes=500)
    explorer = HierarchicalExplorer(tmp_path, budget=budget)

    _candidates, is_incomplete = explorer.explore("module search")
    assert is_incomplete is True
