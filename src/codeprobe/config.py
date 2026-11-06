from __future__ import annotations

import fnmatch
import logging
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

from .schemas import ModelTier, TaskCategory

logger = logging.getLogger(__name__)


class GuardrailsConfig(BaseModel):
    forbidden_files: list[str] = Field(
        default_factory=lambda: [
            ".env*",
            "*.pem",
            "*.key",
            "credentials.json",
            "secrets/*",
        ],
        description="Globs of files forbidden from reading, searching, or modifying.",
    )
    read_only_files: list[str] = Field(
        default_factory=lambda: [
            "package-lock.json",
            "yarn.lock",
            "poetry.lock",
            "uv.lock",
            "*.min.js",
        ],
        description="Globs of files that may only be read, never modified.",
    )


class PolicyConfig(BaseModel):
    require_tests_before_edit: bool = Field(
        default=True,
        description="Require test verification evidence before permitting code modifications.",
    )
    blast_radius_limit: int = Field(
        default=5,
        description="Maximum number of files allowed in a single modification batch before requiring confirmation.",
    )
    max_file_slice_lines: int = Field(
        default=150,
        description="Maximum lines to recommend in a single file slice read.",
    )
    navigation_budget_bytes: int = Field(
        default=250_000,
        description="Maximum preview bytes consumed during tree navigation before marking discovery as incomplete.",
    )
    custom_prohibitions: list[str] = Field(
        default_factory=list,
        description="Custom prohibited action tags injected into routing decisions.",
    )


class ThresholdsConfig(BaseModel):
    default: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description="Default probability threshold for triggering actions.",
    )
    investigation: float | None = Field(default=None, ge=0.0, le=1.0)
    debugging: float | None = Field(default=None, ge=0.0, le=1.0)
    refactoring: float | None = Field(default=None, ge=0.0, le=1.0)
    testing: float | None = Field(default=None, ge=0.0, le=1.0)
    model_routing: float | None = Field(default=None, ge=0.0, le=1.0)


class ModelTiersConfig(BaseModel):
    investigation: ModelTier | None = Field(default=None)
    debugging: ModelTier | None = Field(default=None)
    refactoring: ModelTier | None = Field(default=None)
    testing: ModelTier | None = Field(default=None)
    model_routing: ModelTier | None = Field(default=None)


class ProjectConfig(BaseModel):
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    model_tiers: ModelTiersConfig = Field(default_factory=ModelTiersConfig)
    config_path: str | None = Field(
        default=None, description="Path to loaded config file if discovered"
    )

    def is_file_forbidden(self, filepath: str) -> bool:
        name = Path(filepath).name
        full = filepath.replace("\\", "/")
        return any(
            fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(full, pat)
            for pat in self.guardrails.forbidden_files
        )

    def is_file_read_only(self, filepath: str) -> bool:
        name = Path(filepath).name
        full = filepath.replace("\\", "/")
        return any(
            fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(full, pat)
            for pat in self.guardrails.read_only_files
        )

    def get_threshold(self, category: TaskCategory) -> float:
        cat_val = category.value
        overridden = getattr(self.thresholds, cat_val, None)
        return overridden if overridden is not None else self.thresholds.default

    def get_model_tier_override(self, category: TaskCategory) -> ModelTier | None:
        cat_val = category.value
        return getattr(self.model_tiers, cat_val, None)


def find_config_file(start_path: str | Path | None = None) -> Path | None:
    """
    Locate configuration file by walking upward from current working directory.
    Checks:
    1. .codeprobe/rules.toml
    2. codeprobe.toml
    3. pyproject.toml (containing [tool.codeprobe])
    """
    current = Path(start_path).resolve() if start_path else Path.cwd().resolve()

    while True:
        # 1. .codeprobe/rules.toml
        dot_rules = current / ".codeprobe" / "rules.toml"
        if dot_rules.is_file():
            return dot_rules

        # 2. codeprobe.toml
        root_toml = current / "codeprobe.toml"
        if root_toml.is_file():
            return root_toml

        # 3. pyproject.toml
        pyproject = current / "pyproject.toml"
        if pyproject.is_file():
            try:
                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)
                if "tool" in data and "codeprobe" in data["tool"]:
                    return pyproject
            except (tomllib.TOMLDecodeError, OSError) as exc:
                logger.debug("Failed reading pyproject.toml: %s", exc)

        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def load_config(
    path: str | Path | None = None,
    start_dir: str | Path | None = None,
) -> ProjectConfig:
    """
    Load project configuration from specified path or auto-discovered location.
    """
    target_path = Path(path).resolve() if path else find_config_file(start_dir)

    if not target_path or not target_path.is_file():
        return ProjectConfig()

    try:
        with open(target_path, "rb") as f:
            raw_data = tomllib.load(f)

        if target_path.name == "pyproject.toml":
            config_dict = raw_data.get("tool", {}).get("codeprobe", {})
        else:
            config_dict = raw_data

        config = ProjectConfig(**config_dict)
        config.config_path = str(target_path)
        return config
    except (tomllib.TOMLDecodeError, OSError, TypeError, ValueError) as exc:
        logger.warning(
            "Failed to parse config at %s: %s. Using default config.", target_path, exc
        )
        return ProjectConfig(config_path=str(target_path))


def generate_default_config_toml() -> str:
    """
    Generate commented starter TOML configuration for .codeprobe/rules.toml.
    """
    return """# .codeprobe/rules.toml - codeprobe configuration and policy guardrails

[guardrails]
# Globs of files forbidden from reading, searching, or modifying
forbidden_files = [
    ".env*",
    "*.pem",
    "*.key",
    "credentials.json",
    "secrets/*",
]

# Globs of files that may only be read, never modified
read_only_files = [
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    "uv.lock",
    "*.min.js",
]

[policy]
# Require test execution evidence before allowing code modifications
require_tests_before_edit = true

# Warn or restrict edits touching more than N files simultaneously
blast_radius_limit = 5

# Maximum lines to recommend in a single file slice read
max_file_slice_lines = 150

# Maximum navigation preview bytes before reporting incomplete discovery (default 250 KB)
navigation_budget_bytes = 250000

# Custom prohibited action tags injected into all routing decisions
custom_prohibitions = []

[thresholds]
default = 0.70
investigation = 0.70
debugging = 0.75
refactoring = 0.80
testing = 0.70

[model_tiers]
# Override default model tier per category (fast_infer, standard, reasoning)
investigation = "fast_infer"
debugging = "reasoning"
refactoring = "reasoning"
testing = "standard"
"""
