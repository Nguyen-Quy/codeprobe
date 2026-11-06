from __future__ import annotations

from .core.matrices import INVESTIGATION_MATRIX, MATRICES, DecisionMatrix
from .core.router import LayaDecisionRouter
from .core.synthesizer import StateSynthesizer
from .schemas import DecisionRequest, TaskCategory

# Legacy static questions export for backward compatibility
QUESTIONS = INVESTIGATION_MATRIX.questions


class LayaRouter:
    """
    Backward-compatible wrapper around Laya router for codeprobe.
    Delegates to LayaDecisionRouter for calibrated decision probabilities.
    """

    def __init__(self) -> None:
        self.decision_router = LayaDecisionRouter()

    def decide(self, state: str) -> dict:
        extracted_files = StateSynthesizer.extract_file_paths(state)
        req = DecisionRequest(
            user_goal=state[:200] if state else "investigation",
            task_category=TaskCategory.INVESTIGATION,
            collected_evidence=[state] if state else [],
            known_files=extracted_files,
        )
        response = self.decision_router.route(req)
        return {
            "answers": {k: {"noul": v} for k, v in response.raw_probabilities.items()}
        }

    @staticmethod
    def probability(result: dict, key: str) -> float:
        try:
            return float(result["answers"][key]["noul"])
        except (KeyError, TypeError, ValueError):
            return 0.0

    def yes(self, result: dict, key: str, threshold: float = 0.70) -> bool:
        return self.probability(result, key) >= threshold


__all__ = [
    "MATRICES",
    "QUESTIONS",
    "DecisionMatrix",
    "LayaDecisionRouter",
    "LayaRouter",
]
