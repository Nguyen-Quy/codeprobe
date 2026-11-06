from __future__ import annotations

from pathlib import Path

from codeprobe.core.learning import FeedbackLearner
from codeprobe.schemas import InvestigationFeedback, InvestigationResult


def test_feedback_learner_trajectory_and_weights(tmp_path: Path):
    res = InvestigationResult(
        investigation_id=FeedbackLearner.generate_investigation_id(),
        user_goal="Refactor auth middleware in TypeScript",
        strategy="REFACTOR_ANALYSIS",
        confidence=0.9,
        summary="Found auth.ts and user.ts",
        examined_files=["src/auth.ts", "src/user.ts"],
        discovered_symbols=["authenticateUser", "UserInterface"],
        is_sufficient=True,
    )
    FeedbackLearner.record_trajectory(res, tmp_path)
    traj_file = tmp_path / ".codeprobe" / "trajectories.jsonl"
    assert traj_file.is_file()
    assert "auth.ts" in traj_file.read_text()

    # Submit positive feedback
    fb = InvestigationFeedback(
        investigation_id=res.investigation_id,
        score=5,
        feedback_text="Spot on analysis",
        helpful_files=["src/auth.ts"],
        workspace_path=str(tmp_path),
    )
    resp = FeedbackLearner.process_feedback(fb)
    assert resp.status == "success"
    assert resp.learned_updates_count > 0

    weights = FeedbackLearner.load_learned_weights(tmp_path)
    assert weights["sample_count"] == 1
    assert weights["ext_boosts"][".ts"] > 1.2
