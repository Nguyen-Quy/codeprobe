from __future__ import annotations

from dataclasses import dataclass, field

from .declarations import DeclarationUnit


@dataclass
class RelationshipLink:
    source_file: str
    caller_unit: str
    target_symbol: str
    target_file: str
    confidence: float = 0.85


@dataclass
class RelationshipReport:
    links: list[RelationshipLink] = field(default_factory=list)
    donor_files: list[str] = field(default_factory=list)
    retracted_files: list[str] = field(default_factory=list)

    def format_summary(self) -> str:
        lines = [
            f"🔗 Cross-File Relationships ({len(self.links)} links):",
        ]
        for lk in self.links[:10]:
            lines.append(
                f"   • {lk.caller_unit} ({lk.source_file}) ──calls──> {lk.target_symbol} ({lk.target_file})"
            )
        if self.donor_files:
            lines.append(f"   Donor Evidence Files: {', '.join(self.donor_files[:5])}")
        if self.retracted_files:
            lines.append(
                f"   Retracted (False Positive) Files: {', '.join(self.retracted_files[:5])}"
            )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "links": [
                {
                    "source_file": link.source_file,
                    "caller_unit": link.caller_unit,
                    "target_symbol": link.target_symbol,
                    "target_file": link.target_file,
                    "confidence": link.confidence,
                }
                for link in self.links
            ],
            "donor_files": self.donor_files,
            "retracted_files": self.retracted_files,
        }


class RelationshipLinker:
    """
    Traces caller-callee and cross-file relationships to identify donor evidence files
    and retract irrelevant false-positive files.
    """

    @classmethod
    def trace_relationships(
        cls,
        declarations: list[DeclarationUnit],
        all_candidate_files: list[str],
        query_tokens: list[str],
    ) -> RelationshipReport:
        links: list[RelationshipLink] = []
        donor_files: set[str] = set()
        active_files_with_matches: set[str] = set()

        # Build symbol table: symbol_name -> list of (file_path, DeclarationUnit)
        symbol_map: dict[str, list[DeclarationUnit]] = {}
        for decl in declarations:
            active_files_with_matches.add(decl.file_path)
            symbol_map.setdefault(decl.name, []).append(decl)

        # Connect callers to callees across files
        for decl in declarations:
            for call in decl.calls:
                targets = symbol_map.get(call, [])
                for target_decl in targets:
                    if target_decl.file_path != decl.file_path:
                        links.append(
                            RelationshipLink(
                                source_file=decl.file_path,
                                caller_unit=decl.name,
                                target_symbol=call,
                                target_file=target_decl.file_path,
                            )
                        )
                        donor_files.add(target_decl.file_path)

        # Identify retracted files (candidate files that had no matches and no relationship links)
        retracted: list[str] = []
        for cf in all_candidate_files:
            if cf not in active_files_with_matches and cf not in donor_files:
                # Check if file name at least matches query tokens
                cf_lower = cf.lower()
                if not any(t.lower() in cf_lower for t in query_tokens):
                    retracted.append(cf)

        return RelationshipReport(
            links=links,
            donor_files=sorted(donor_files),
            retracted_files=sorted(retracted),
        )
