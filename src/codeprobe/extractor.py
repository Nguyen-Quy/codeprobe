from __future__ import annotations

import re
from pathlib import Path

# Common English and Vietnamese stopwords to filter out from raw natural language queries
STOPWORDS: set[str] = {
    # English stopwords
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "am",
    "an",
    "and",
    "any",
    "are",
    "aren't",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "below",
    "between",
    "both",
    "but",
    "by",
    "can",
    "can't",
    "cannot",
    "could",
    "couldn't",
    "did",
    "didn't",
    "do",
    "does",
    "doesn't",
    "doing",
    "don't",
    "down",
    "during",
    "each",
    "explain",
    "few",
    "find",
    "for",
    "from",
    "further",
    "get",
    "had",
    "hadn't",
    "has",
    "hasn't",
    "have",
    "haven't",
    "having",
    "he",
    "her",
    "here",
    "hers",
    "herself",
    "him",
    "himself",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "isn't",
    "it",
    "its",
    "itself",
    "just",
    "know",
    "let",
    "look",
    "me",
    "more",
    "most",
    "mustn't",
    "my",
    "myself",
    "no",
    "nor",
    "not",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "ought",
    "our",
    "ours",
    "ourselves",
    "out",
    "over",
    "own",
    "please",
    "same",
    "see",
    "shall",
    "shan't",
    "she",
    "should",
    "shouldn't",
    "show",
    "so",
    "some",
    "such",
    "tell",
    "than",
    "that",
    "the",
    "their",
    "theirs",
    "them",
    "themselves",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "very",
    "was",
    "wasn't",
    "we",
    "were",
    "weren't",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "whom",
    "why",
    "with",
    "won't",
    "would",
    "wouldn't",
    "you",
    "your",
    "yours",
    "yourself",
    "yourselves",
    "check",
    "progress",
    "summary",
    "code",
    "file",
    "files",
    "project",
    "repo",
    "repository",
    # Vietnamese stopwords
    "là",
    "của",
    "và",
    "các",
    "những",
    "được",
    "có",
    "tại",
    "trong",
    "cho",
    "về",
    "với",
    "này",
    "cái",
    "đó",
    "thì",
    "mà",
    "như",
    "nào",
    "gì",
    "làm",
    "tới",
    "đâu",
    "rồi",
    "sao",
    "sao ko",
    "ko",
    "không",
    "thấy",
    "hãy",
    "xem",
    "tìm",
    "tra",
    "cứu",
    "kiểm",
    "tổng",
    "hợp",
    "báo",
    "cáo",
    "tóm",
    "tắt",
    "ở",
    "ra",
    "vào",
    "đến",
    "đi",
    "biết",
    "thế",
    "ai",
    "bao",
    "nhiêu",
    "chưa",
    "đang",
    "đã",
    "sẽ",
    "phải",
    "nên",
}


class QueryKeywordExtractor:
    """
    Extracts high-precision search tokens, file path candidates, version/phase numbers,
    and code symbols from natural language user queries.
    """

    @classmethod
    def extract_search_tokens(cls, query: str) -> list[str]:
        """
        Extract ranked search tokens suitable for ripgrep / codebase search.
        """
        tokens: list[str] = []
        seen: set[str] = set()

        def add_token(t: str) -> None:
            cleaned = t.strip().strip("'\"`.,:;()[]{}")
            if not cleaned or len(cleaned) < 2:
                return
            if cleaned.lower() in STOPWORDS:
                return
            if cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                tokens.append(cleaned)

        # 1. Quoted substrings (highest precision)
        for quoted in re.findall(r'["\'`]([^"\'`]+)["\'`]', query):
            add_token(quoted)

        # 2. Phase and Version patterns (e.g. "phase 12.1", "12.1", "v2.0", "phase-3")
        for match in re.findall(r"(?i)(?:phase[-_\s]+)?(\d+(?:\.\d+)+[a-z]?)", query):
            add_token(match)
            add_token(f"phase {match}")
            add_token(f"phase-{match}")

        # 3. File paths / file references (e.g. ".planning", "STATE.md", "ROADMAP.md", "src/codeprobe/config.py")
        for path_match in re.findall(
            r"(?:\.?[\w\-]+/)+[\w\-]+(?:\.[\w\-]+)?|\b[\w\-]+\.(?:py|md|toml|json|ts|js|go|rs|yaml|yml|sql|txt)\b|\.planning\b|\broadmap\b|\bstate\b",
            query,
            re.IGNORECASE,
        ):
            add_token(path_match)

        # 4. Code symbols: CamelCase, snake_case, UPPER_CASE, dotted identifiers
        for symbol in re.findall(
            r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b|\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b|\b[a-z0-9]+_[a-z0-9_]+\b|\b[A-Z0-9]+_[A-Z0-9_]+\b",
            query,
        ):
            add_token(symbol)

        # 5. Exception / Error types (e.g. ZeroDivisionError, TypeError)
        for err in re.findall(
            r"\b[A-Z][a-zA-Z0-9]*(?:Error|Exception|Warning|Fault|NotFound|Timeout)\b",
            query,
        ):
            add_token(err)

        # 6. Remaining significant alphanumeric words
        words = re.findall(r"\b[a-zA-Z0-9_\-\.]{3,}\b", query)
        for w in words:
            if w.lower() not in STOPWORDS and not w.isdigit():
                add_token(w)

        return tokens[:8]

    @classmethod
    def discover_workspace_paths(cls, query: str, root_path: Path) -> list[str]:
        """
        Scan workspace directory for paths mentioned or hinted in the query.
        For example: .planning, roadmap, state, specific phase folders.
        """
        discovered: list[str] = []
        q_lower = query.lower()

        # Check for .planning directory if query mentions planning or phase
        if any(
            k in q_lower
            for k in [
                ".planning",
                "planning",
                "phase",
                "roadmap",
                "state",
                "summary",
                "plan",
                "spec",
            ]
        ):
            planning_dir = root_path / ".planning"
            if planning_dir.is_dir():
                for p in planning_dir.rglob("*"):
                    if p.is_file() and not p.name.startswith("."):
                        rel = str(p.relative_to(root_path))
                        # Prioritize files matching phase numbers if any (e.g. 12.1, 01, 12, etc.)
                        phase_matches = re.findall(r"\b\d+(?:\.\d+)*\b", query)
                        if phase_matches:
                            if any(pm in rel for pm in phase_matches):
                                discovered.insert(0, rel)
                            else:
                                discovered.append(rel)
                        else:
                            discovered.append(rel)

        # Check for top-level docs like ROADMAP.md, README.md, STATE.md, PROJECT.md, etc.
        for doc_name in [
            "ROADMAP.md",
            "STATE.md",
            "PROJECT.md",
            "README.md",
            "ARCHITECTURE.md",
            "AI-SPEC.md",
            "UI-SPEC.md",
            "GEMINI.md",
            "AGENTS.md",
        ]:
            doc_file = root_path / doc_name
            if doc_file.is_file() and (
                doc_name.lower() in q_lower
                or any(
                    k in q_lower
                    for k in [
                        "roadmap",
                        "state",
                        "phase",
                        "overview",
                        "project",
                        "summary",
                        "plan",
                    ]
                )
            ):
                rel = str(doc_file.relative_to(root_path))
                if rel not in discovered:
                    discovered.append(rel)

        return discovered[:12]
