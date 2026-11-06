from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from ..schemas import FeedbackResponse, InvestigationFeedback, InvestigationResult
from ..tools import get_workspace_root

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS: dict[str, Any] = {
    "version": "1.0",
    "path_boosts": {
        ".planning/": 1.5,
        "src/": 1.2,
        "app/": 1.2,
        "apps/": 1.2,
        "models/": 1.3,
        "services/": 1.2,
        "controllers/": 1.2,
        "views/": 1.2,
        "routes/": 1.2,
        "pkg/": 1.1,
    },
    "ext_boosts": {
        ".ts": 1.2,
        ".tsx": 1.2,
        ".rs": 1.2,
        ".go": 1.2,
        ".py": 1.2,
        ".md": 1.3,
        ".json": 0.9,
    },
    "negative_patterns": [
        "node_modules",
        ".git",
        "__pycache__",
        "dist",
        "build",
        "target",
        ".lock",
    ],
    "sample_count": 0,
    "last_updated": 0,
}


def _get_codeprobe_dir(workspace_path: Path | str | None = None) -> Path:
    ws = Path(workspace_path).resolve() if workspace_path else get_workspace_root()
    cp_dir = ws / ".codeprobe"
    try:
        cp_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.debug("Failed to create .codeprobe dir in workspace: %s", exc)
        cp_dir = Path.home() / ".codeprobe"
        cp_dir.mkdir(parents=True, exist_ok=True)
    return cp_dir


class FeedbackLearner:
    """
    Self-training online reinforcement learning engine for CodeProbe.
    Tracks exploration trajectories, logs agent/user feedback, and calibrates
    path/extension/symbol weights continuously.
    """

    @classmethod
    def generate_investigation_id(cls) -> str:
        return f"inv_{int(time.time())}_{uuid.uuid4().hex[:8]}"

    @classmethod
    def record_trajectory(
        cls,
        result: InvestigationResult,
        workspace_path: Path | str | None = None,
    ) -> None:
        """
        Record the investigation trajectory to .codeprobe/trajectories.jsonl
        """
        try:
            cp_dir = _get_codeprobe_dir(workspace_path)
            traj_file = cp_dir / "trajectories.jsonl"

            entry = {
                "investigation_id": result.investigation_id,
                "timestamp": time.time(),
                "user_goal": result.user_goal,
                "strategy": result.strategy,
                "confidence": result.confidence,
                "steps_executed": result.steps_executed,
                "examined_files": result.examined_files,
                "discovered_symbols": result.discovered_symbols,
                "is_sufficient": result.is_sufficient,
            }
            with traj_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except (OSError, TypeError, ValueError) as exc:
            logger.debug("Error recording trajectory: %s", exc)

    @classmethod
    def load_learned_weights(
        cls, workspace_path: Path | str | None = None
    ) -> dict[str, Any]:
        """
        Load learned weights from .codeprobe/learned_weights.json with fallback defaults.
        """
        cp_dir = _get_codeprobe_dir(workspace_path)
        weights_file = cp_dir / "learned_weights.json"
        if weights_file.is_file():
            try:
                data = json.loads(weights_file.read_text(encoding="utf-8"))
                # Merge with defaults
                merged = dict(DEFAULT_WEIGHTS)
                merged.update(data)
                return merged
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                logger.debug("Error loading learned weights, using defaults: %s", exc)
        return dict(DEFAULT_WEIGHTS)

    @classmethod
    def process_feedback(cls, feedback: InvestigationFeedback) -> FeedbackResponse:
        """
        Process agent or human feedback, log to feedback.jsonl, and update weight matrices.
        """
        cp_dir = _get_codeprobe_dir(feedback.workspace_path)
        feedback_file = cp_dir / "feedback.jsonl"
        weights_file = cp_dir / "learned_weights.json"

        # 1. Log Feedback Entry
        entry = {
            "investigation_id": feedback.investigation_id,
            "timestamp": time.time(),
            "score": feedback.score,
            "feedback_text": feedback.feedback_text,
            "helpful_files": feedback.helpful_files or [],
            "unhelpful_files": feedback.unhelpful_files or [],
        }
        try:
            with feedback_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Failed to append to feedback.jsonl: %s", exc)

        # 2. Calibrate Weights
        weights = cls.load_learned_weights(feedback.workspace_path)
        path_boosts = weights.setdefault("path_boosts", {})
        ext_boosts = weights.setdefault("ext_boosts", {})
        updates_count = 0

        # Positive Feedback (score 4 or 5)
        if feedback.score >= 4:
            helpful = feedback.helpful_files or []
            for file_path in helpful:
                p = Path(file_path)
                ext = p.suffix.lower()
                if ext:
                    current_ext_w = ext_boosts.get(ext, 1.0)
                    ext_boosts[ext] = min(round(current_ext_w + 0.15, 2), 3.5)
                    updates_count += 1

                for part in p.parts[:-1]:
                    key = f"{part}/"
                    current_p_w = path_boosts.get(key, 1.0)
                    path_boosts[key] = min(round(current_p_w * 1.25, 2), 5.0)
                    updates_count += 1

        # Negative Feedback (score 1 or 2)
        elif feedback.score <= 2:
            unhelpful = feedback.unhelpful_files or []
            for file_path in unhelpful:
                p = Path(file_path)
                for part in p.parts[:-1]:
                    key = f"{part}/"
                    current_p_w = path_boosts.get(key, 1.0)
                    path_boosts[key] = max(round(current_p_w * 0.75, 2), 0.1)
                    updates_count += 1

        weights["sample_count"] = weights.get("sample_count", 0) + 1
        weights["last_updated"] = time.time()

        try:
            weights_file.write_text(
                json.dumps(weights, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Failed to save learned_weights.json: %s", exc)

        msg = (
            f"Feedback recorded for {feedback.investigation_id}. "
            f"Applied {updates_count} weight adjustments. Current sample count: {weights['sample_count']}."
        )
        return FeedbackResponse(
            status="success",
            investigation_id=feedback.investigation_id,
            learned_updates_count=updates_count,
            message=msg,
        )
