import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from codeprobe.cli import main


def test_cli_route_command(capsys):
    test_args = ["codeprobe", "route", "Find", "authentication", "token", "generator"]
    with patch.object(sys, "argv", test_args):
        main()

    captured = capsys.readouterr()
    assert captured.out.strip() != ""
    data = json.loads(captured.out)
    assert "strategy" in data
    assert "confidence" in data
    assert "recommended_actions" in data


def test_cli_serve_help(capsys):
    test_args = ["codeprobe", "serve", "--help"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "--sse" in captured.out
    assert "--http" in captured.out
    assert "--port" in captured.out


def test_cli_test_matrix_command(capsys):
    test_args = ["codeprobe", "test-matrix", "--category", "investigation"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "Cold Investigation" in captured.out
    assert "PASSED" in captured.out


def test_cli_config_command(capsys):
    test_args = ["codeprobe", "config", "--json"]
    with patch.object(sys, "argv", test_args):
        main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "guardrails" in data
    assert "policy" in data
    assert "thresholds" in data


def test_cli_init_command(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    test_args = ["codeprobe", "init"]
    with patch.object(sys, "argv", test_args):
        main()

    captured = capsys.readouterr()
    assert "Successfully initialized" in captured.out
    created_file = tmp_path / ".codeprobe" / "rules.toml"
    assert created_file.is_file()
    assert "[guardrails]" in created_file.read_text()
