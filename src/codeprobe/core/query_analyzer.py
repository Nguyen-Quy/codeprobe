from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum

from ..llm import LLMError, chat
from ..schemas import ModelTier, QueryDomain

logger = logging.getLogger(__name__)


class QueryStatus(str, Enum):
    VALID = "VALID"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


@dataclass
class QueryAnalysisResult:
    status: QueryStatus
    refined_query: str = ""
    domain: QueryDomain = QueryDomain.APPLICATION_LOGIC
    target_symbols: list[str] = field(default_factory=list)
    file_hints: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    clarification_questions: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    raw_reasoning: str = ""


# Generic ambiguous query patterns (English & Vietnamese)
AMBIGUOUS_PATTERNS = [
    r"^(?:fix\s+this|fix\s+bug|check\s+code|make\s+it\s+better|find\s+bugs?|what\s+is\s+wrong|debug(?:\s+it)?|help(?:\s+me)?|look\s+at\s+this|optimize\s+this|improve\s+this)[\s\?!.]*$",
    r"^(?:sửa\s+lỗi|xem\s+giùm|kiểm\s+tra\s+code|fix\s+giùm|có\s+lỗi\s+gì\s+không|chạy\s+đi|giúp\s+tao(?:\s+với)?|sửa\s+đi|xem\s+thử)[\s\?!.]*$",
]

DEFAULT_CLARIFICATION_QUESTIONS = [
    "Which specific component, function, or file are you investigating?",
    "What is the expected behavior, error message, or stack trace?",
    "Can you provide a symbol name, endpoint, or reproduction steps?",
]


class PreFlightQueryAnalyzer:
    """
    Step 0 Query Analyzer that analyzes user intent with local LLM (Qwen 3B)
    or deterministic heuristics, flagging ambiguous queries before consuming search budgets.
    """

    def __init__(self, timeout: int = 5):
        self.timeout = timeout

    def analyze(self, query: str, workspace_path: str = "") -> QueryAnalysisResult:
        trimmed = query.strip()
        if not trimmed:
            return QueryAnalysisResult(
                status=QueryStatus.NEEDS_CLARIFICATION,
                clarification_questions=DEFAULT_CLARIFICATION_QUESTIONS,
                raw_reasoning="Query is empty.",
            )

        # 1. Fast regex detection for blatantly ambiguous queries
        for pattern in AMBIGUOUS_PATTERNS:
            if re.match(pattern, trimmed, re.IGNORECASE):
                return QueryAnalysisResult(
                    status=QueryStatus.NEEDS_CLARIFICATION,
                    clarification_questions=DEFAULT_CLARIFICATION_QUESTIONS,
                    raw_reasoning=f"Query '{trimmed}' matches generic unanchored query pattern.",
                )

        # 2. Attempt fast LLM analysis (Step 0)
        try:
            llm_result = self._analyze_with_llm(trimmed)
            if llm_result:
                return llm_result
        except (LLMError, OSError, ValueError, RuntimeError) as exc:
            logger.debug("Step 0 LLM analyzer skipped or timed out: %s. Using heuristic.", exc)

        # 3. Deterministic Heuristic Fallback
        return self._analyze_heuristically(trimmed, workspace_path)

    def _analyze_with_llm(self, query: str) -> QueryAnalysisResult | None:
        system_prompt = (
            "You are a code reconnaissance query analyzer. Given the developer's query, determine if it has "
            "sufficient context to locate code symbols/files, or if it is too ambiguous and needs clarification. "
            "Output ONLY a valid JSON object matching this schema:\n"
            "{\n"
            '  "status": "VALID" | "NEEDS_CLARIFICATION",\n'
            '  "domain": "APPLICATION_LOGIC" | "INFRA_DEVOPS" | "HYBRID",\n'
            '  "refined_query": "concise query for code search",\n'
            '  "target_symbols": ["symbol_name"],\n'
            '  "file_hints": ["path_or_file.ext"],\n'
            '  "hypotheses": ["brief hypothesis on implementation"],\n'
            '  "clarification_questions": ["question if NEEDS_CLARIFICATION"]\n'
            "}"
        )
        input_text = f"Analyze developer query: {query}"

        # Fast tier inference with tight token limit
        raw = chat(
            system_prompt=system_prompt,
            input_text=input_text,
            tier=ModelTier.FAST_INFER,
            timeout=self.timeout,
            temperature=0.1,
            max_tokens=160,
        )

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return None

        data = json.loads(match.group(0))
        status_str = data.get("status", "VALID").upper()
        status = QueryStatus.NEEDS_CLARIFICATION if "CLARIF" in status_str else QueryStatus.VALID

        domain_str = data.get("domain", "APPLICATION_LOGIC").upper()
        if "INFRA" in domain_str or "DEVOPS" in domain_str:
            domain = QueryDomain.INFRA_DEVOPS
        elif "HYBRID" in domain_str:
            domain = QueryDomain.HYBRID
        else:
            domain = QueryDomain.APPLICATION_LOGIC

        questions = data.get("clarification_questions") or []
        if status == QueryStatus.NEEDS_CLARIFICATION and not questions:
            questions = DEFAULT_CLARIFICATION_QUESTIONS

        return QueryAnalysisResult(
            status=status,
            refined_query=data.get("refined_query", query),
            domain=domain,
            target_symbols=data.get("target_symbols") or [],
            file_hints=data.get("file_hints") or [],
            hypotheses=data.get("hypotheses") or [],
            clarification_questions=questions,
            raw_reasoning=raw,
        )

    def _analyze_heuristically(self, query: str, workspace_path: str = "") -> QueryAnalysisResult:
        symbols: list[str] = []
        files: list[str] = []

        # Find snake_case, camelCase, PascalCase, or dot/slash paths
        token_candidates = re.findall(r"[A-Za-z0-9_\-\./]+", query)
        for tok in token_candidates:
            if re.search(r"\.(?:py|ts|js|go|rs|sh|yaml|yml|json|toml|md)$", tok, re.IGNORECASE):
                files.append(tok)
            elif "_" in tok or (re.search(r"[a-z][A-Z]", tok) and len(tok) > 2):
                symbols.append(tok)

        # Domain classification via GoalDecomposer
        from .recon import GoalDecomposer

        decomposed = GoalDecomposer.decompose(query)
        domain = decomposed.domain

        # If length is very short and no symbols or files were extracted
        words = [w for w in re.findall(r"\w+", query) if len(w) > 2]
        if len(symbols) == 0 and len(files) == 0 and len(words) <= 2:
            # Check if words are generic
            generic_words = {"fix", "code", "bug", "help", "error", "issue", "check", "run", "test", "lỗi", "sửa"}
            if all(w.lower() in generic_words for w in words):
                return QueryAnalysisResult(
                    status=QueryStatus.NEEDS_CLARIFICATION,
                    clarification_questions=DEFAULT_CLARIFICATION_QUESTIONS,
                    raw_reasoning="Deterministic heuristic detected zero code symbols and generic vocabulary.",
                )

        hypotheses = []
        if symbols:
            hypotheses.append(f"Investigate implementation and usage of symbol '{symbols[0]}'")
        elif files:
            hypotheses.append(f"Examine structure and definitions within '{files[0]}'")
        else:
            hypotheses.append(f"Search codebase for concepts matching: {query}")

        return QueryAnalysisResult(
            status=QueryStatus.VALID,
            refined_query=query,
            domain=domain,
            target_symbols=symbols,
            file_hints=files,
            hypotheses=hypotheses,
        )

