from __future__ import annotations

from pathlib import Path

from codeprobe.inventory import scan_inventory


def test_scan_inventory_basic(tmp_path: Path):
    # Setup sample directory structure
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("print('hello world')\n", encoding="utf-8")
    (src_dir / "utils.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_main.py").write_text(
        "def test_ok(): assert True\n", encoding="utf-8"
    )

    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")

    # Add ignored file & binary file
    (tmp_path / "app.exe").write_bytes(b"\x00\x01\x02")
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("git config", encoding="utf-8")

    inv = scan_inventory(tmp_path)

    assert inv.total_files == 4  # main.py, utils.py, test_main.py, README.md
    assert inv.total_bytes > 0
    assert "src" in inv.breakdown_by_dir
    assert inv.breakdown_by_dir["src"].files == 2
    assert "tests" in inv.breakdown_by_dir
    assert inv.breakdown_by_dir["tests"].files == 1
    assert inv.language_distribution.get("Python") == 3
    assert inv.language_distribution.get("Markdown") == 1
    assert inv.excluded_files_count >= 1  # app.exe and .git ignored


def test_scan_inventory_with_excludes(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("code", encoding="utf-8")
    (src_dir / "test_dummy.py").write_text("test", encoding="utf-8")

    inv = scan_inventory(tmp_path, exclude_patterns=["*dummy*"])
    assert inv.total_files == 1
    assert inv.breakdown_by_dir["src"].files == 1


def test_inventory_formatting_and_dict(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.ts").write_text("const x = 1;\n", encoding="utf-8")

    inv = scan_inventory(tmp_path)
    summary_text = inv.format_human_summary()

    assert "Workspace Inventory for:" in summary_text
    assert "src/" in summary_text
    assert "TypeScript" in summary_text

    data = inv.to_dict()
    assert data["total_files"] == 1
    assert "breakdown_by_dir" in data
    assert "src" in data["breakdown_by_dir"]
    assert data["breakdown_by_dir"]["src"]["files"] == 1
