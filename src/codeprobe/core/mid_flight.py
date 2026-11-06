from __future__ import annotations

import logging

from ..llm import LLMError, chat
from ..schemas import ModelTier

logger = logging.getLogger(__name__)


class MidFlightAnalyst:
    """
    Hop-by-hop reasoning analyst powered by local Qwen 3B.
    Evaluates current evidence state, missing aspects, and steers subsequent hops.
    """

    def __init__(self, timeout: int = 5):
        self.timeout = timeout

    def suggest_next_hop_query(
        self,
        query: str,
        missing_aspects: list[str],
        examined_files: list[str],
        discovered_symbols: list[str],
    ) -> str | None:
        """
        Ask local model for the optimal next search query given missing context.
        Returns a concise 2-5 word search query or None if skipped/failed.
        """
        system_prompt = (
            "You are an expert codebase recon analyst. We are investigating a repository to fulfill a developer request. "
            "Given what has been found and what context is still missing, formulate a 2-4 word search query (symbols, keywords, or filenames) "
            "for the next reconnaissance hop. Output ONLY the search query string, without quotes or markdown formatting."
        )

        files_str = ", ".join(examined_files[-4:]) if examined_files else "none"
        symbols_str = ", ".join(discovered_symbols[:6]) if discovered_symbols else "none"
        missing_str = ", ".join(missing_aspects) if missing_aspects else "none"

        user_input = (
            f"Goal: {query}\n"
            f"Examined files: {files_str}\n"
            f"Discovered symbols: {symbols_str}\n"
            f"Missing context aspects: {missing_str}\n"
            f"Next targeted search query:"
        )

        try:
            raw = chat(
                system_prompt=system_prompt,
                input_text=user_input,
                tier=ModelTier.FAST_INFER,
                timeout=self.timeout,
                temperature=0.2,
                max_tokens=30,
            )
            cleaned = raw.strip().strip('"').strip("'").splitlines()[0].strip()
            # Sanitize: if output is too long or contains sentences, reject
            if 2 <= len(cleaned.split()) <= 8:
                return cleaned
            return None
        except (LLMError, OSError, ValueError, RuntimeError) as exc:
            logger.debug("MidFlightAnalyst skipped or timed out: %s", exc)
            return None
