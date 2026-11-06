from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

EvidenceKind = Literal[
    "source_code",
    "search_match",
    "git_change",
    "config_entry",
    "relationship",
    "command_output",
]

EvidenceStatus = Literal["FACT", "HYPOTHESIS", "GAP"]


@dataclass
class EvidenceItem:
    source: str
    content: str
    kind: EvidenceKind
    line_start: int | None = None
    line_end: int | None = None
    content_hash: str = ""
    status: EvidenceStatus = "FACT"
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.content_hash:
            normalized = f"{self.source}:{self.line_start}:{self.line_end}:{self.content.strip()}"
            self.content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[
                :16
            ]


class EvidenceManager:
    """
    Manages structured, deduplicated repository evidence with tri-state status
    (FACT, HYPOTHESIS, GAP) and progressive code skeletonization.
    """

    def __init__(self) -> None:
        self._items: dict[str, EvidenceItem] = {}

    def add(
        self,
        source: str,
        content: str,
        kind: EvidenceKind,
        line_start: int | None = None,
        line_end: int | None = None,
        status: EvidenceStatus = "FACT",
        confidence: float = 1.0,
    ) -> EvidenceItem:
        normalized = f"{source}:{line_start}:{line_end}:{content.strip()}"
        chash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

        if chash in self._items:
            existing = self._items[chash]
            # Upgrade status or confidence if new observation is higher
            existing.confidence = max(existing.confidence, confidence)
            return existing

        item = EvidenceItem(
            source=source,
            content=content,
            kind=kind,
            line_start=line_start,
            line_end=line_end,
            content_hash=chash,
            status=status,
            confidence=confidence,
        )
        self._items[chash] = item
        return item

    def all_items(self) -> list[EvidenceItem]:
        return list(self._items.values())

    def facts(self) -> list[EvidenceItem]:
        return [i for i in self._items.values() if i.status == "FACT"]

    def hypotheses(self) -> list[EvidenceItem]:
        return [i for i in self._items.values() if i.status == "HYPOTHESIS"]

    def gaps(self) -> list[EvidenceItem]:
        return [i for i in self._items.values() if i.status == "GAP"]

    @classmethod
    def skeletonize_code(cls, code: str, max_body_lines: int = 10) -> str:
        """
        Token Firewall: Strips repetitive inner body statements, keeping signatures,
        branch logic, returns, and structural anchors.
        """
        lines = code.splitlines()
        if len(lines) <= max_body_lines:
            return code

        retained: list[str] = []

        for idx, line in enumerate(lines):
            stripped = line.strip()

            # Keep definition headers
            if any(
                stripped.startswith(prefix)
                for prefix in (
                    "def ",
                    "class ",
                    "async def ",
                    "fn ",
                    "pub fn ",
                    "struct ",
                    "impl ",
                    "type ",
                    "interface ",
                    "export ",
                    "export default",
                )
            ):
                retained.append(line)
                continue

            # Keep docstrings or comments
            if (
                '"""' in stripped
                or "'''" in stripped
                or stripped.startswith(("//", "#"))
            ):
                retained.append(line)
                continue

            # Keep control flow anchors & returns
            if any(
                stripped.startswith(k)
                for k in (
                    "return",
                    "yield",
                    "raise",
                    "throw",
                    "match ",
                    "if ",
                    "elif ",
                    "else:",
                    "switch ",
                )
            ):
                retained.append(line)
                continue

            # First 3 and last 2 lines of any block
            if idx < 3 or idx >= len(lines) - 2:
                retained.append(line)
            elif len(retained) > 0 and not retained[-1].endswith(
                "# ... [body pruned for token efficiency]"
            ):
                retained.append("    # ... [body pruned for token efficiency]")

        return "\n".join(retained)

    def export_compact_summary(self, max_items: int = 8) -> str:
        """
        Export a concise markdown section distinguishing FACT, HYPOTHESIS, and GAP.
        """
        sections: list[str] = []

        # 1. Facts
        fact_items = self.facts()[:max_items]
        if fact_items:
            sections.append("#### Verified Facts (Code & Config):")
            for f in fact_items:
                loc = f"{f.source}"
                if f.line_start:
                    loc += f":{f.line_start}"
                    if f.line_end and f.line_end != f.line_start:
                        loc += f"-{f.line_end}"
                preview = self.skeletonize_code(f.content.strip())
                sections.append(f"- **`{loc}`** [{f.kind}]:\n```\n{preview}\n```")

        # 2. Hypotheses
        hypo_items = self.hypotheses()[:max_items]
        if hypo_items:
            sections.append("\n#### Hypotheses (Requiring Verification):")
            for h in hypo_items:
                sections.append(f"- *{h.source}*: {h.content}")

        # 3. Gaps
        gap_items = self.gaps()[:max_items]
        if gap_items:
            sections.append("\n#### Unresolved Questions & Missing Evidence:")
            for g in gap_items:
                sections.append(f"- [ ] {g.content} (Missing in {g.source})")

        return "\n".join(sections)
