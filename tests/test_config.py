from pathlib import Path

from codeprobe.config import (
    ProjectConfig,
    find_config_file,
    generate_default_config_toml,
    load_config,
)
from codeprobe.schemas import ModelTier, TaskCategory


def test_default_config():
    cfg = ProjectConfig()
    assert ".env*" in cfg.guardrails.forbidden_files
    assert "package-lock.json" in cfg.guardrails.read_only_files
    assert cfg.policy.require_tests_before_edit is True
    assert cfg.thresholds.default == 0.70
    assert cfg.get_threshold(TaskCategory.INVESTIGATION) == 0.70


def test_find_and_load_dot_codeprobe_config(tmp_path: Path):
    dot_codeprobe = tmp_path / ".codeprobe"
    dot_codeprobe.mkdir()
    config_file = dot_codeprobe / "rules.toml"
    config_file.write_text("""
[guardrails]
forbidden_files = ["secrets.yaml", "*.key"]
read_only_files = ["custom.lock"]

[policy]
require_tests_before_edit = false
blast_radius_limit = 10
max_file_slice_lines = 200

[thresholds]
default = 0.65
debugging = 0.85

[model_tiers]
debugging = "reasoning"
""")

    discovered = find_config_file(tmp_path)
    assert discovered == config_file

    cfg = load_config(start_dir=tmp_path)
    assert cfg.guardrails.forbidden_files == ["secrets.yaml", "*.key"]
    assert cfg.guardrails.read_only_files == ["custom.lock"]
    assert cfg.policy.require_tests_before_edit is False
    assert cfg.policy.blast_radius_limit == 10
    assert cfg.thresholds.default == 0.65
    assert cfg.get_threshold(TaskCategory.DEBUGGING) == 0.85
    assert (
        cfg.get_model_tier_override(TaskCategory.DEBUGGING) == ModelTier.REASONING_HEAVY
    )


def test_load_pyproject_toml_config(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("""
[tool.codeprobe.guardrails]
forbidden_files = [".env.production"]
read_only_files = ["pnpm-lock.yaml"]

[tool.codeprobe.thresholds]
default = 0.80
""")

    discovered = find_config_file(tmp_path)
    assert discovered == pyproject

    cfg = load_config(start_dir=tmp_path)
    assert cfg.guardrails.forbidden_files == [".env.production"]
    assert cfg.thresholds.default == 0.80


def test_generate_default_config_toml():
    content = generate_default_config_toml()
    assert "[guardrails]" in content
    assert "forbidden_files" in content
    assert "[policy]" in content
    assert "[thresholds]" in content
