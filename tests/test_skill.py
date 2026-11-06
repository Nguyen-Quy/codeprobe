from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from codeprobe.cli import main
from codeprobe.skill import (
    detect_install_destinations,
    get_skill_markdown,
    install_skill,
)


def test_get_skill_markdown_content():
    content = get_skill_markdown()
    assert "name: codeprobe" in content
    assert "description:" in content
    assert "FIRST ACTION RULE" in content
    assert "PROHIBITED ANTIPATTERNS" in content
    assert "MANDATORY CONSUMPTION" in content
    assert "codeprobe files" in content
    assert "codeprobe investigate" in content
    assert "codeprobe route" in content
    assert "codeprobe feedback" in content
    assert "codeprobe_investigate" in content
    assert "codeprobe_files" in content
    assert "codeprobe_decide" in content


def test_detect_install_destinations(tmp_path: Path):
    # Without .agents or .claude
    dests = detect_install_destinations(workspace_root=tmp_path)
    assert any("skills/codeprobe" in str(d) for d in dests)

    # With .agents
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    dests_agents = detect_install_destinations(workspace_root=tmp_path)
    assert (tmp_path / ".agents" / "skills" / "codeprobe") in dests_agents

    # Global
    global_dests = detect_install_destinations(is_global=True)
    assert any(
        ".gemini" in str(d) or ".claude" in str(d) or ".agents" in str(d)
        for d in global_dests
    )


def test_install_skill_custom_dest(tmp_path: Path):
    target_dir = tmp_path / "custom_skill_dir"
    results = install_skill(dest_path=target_dir)

    assert len(results) == 1
    skill_file, success = results[0]
    assert success is True
    assert skill_file == target_dir / "SKILL.md"
    assert skill_file.exists()
    assert "name: codeprobe" in skill_file.read_text(encoding="utf-8")


def test_cli_skill_print(capsys):
    test_args = ["codeprobe", "skill", "--print"]
    with patch.object(sys, "argv", test_args):
        main()

    captured = capsys.readouterr()
    assert "name: codeprobe" in captured.out
    assert "FIRST ACTION RULE" in captured.out


def test_cli_skill_dest_install(tmp_path: Path, capsys):
    target_dir = tmp_path / "agent_skills" / "codeprobe"
    test_args = ["codeprobe", "skill", "--dest", str(target_dir)]
    with patch.object(sys, "argv", test_args):
        main()

    captured = capsys.readouterr()
    assert "Successfully installed CodeProbe skill" in captured.out
    assert (target_dir / "SKILL.md").exists()
