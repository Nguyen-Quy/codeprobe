from __future__ import annotations

from codeprobe.core.declarations import DeclarationUnit
from codeprobe.core.relationships import RelationshipLinker


def test_relationship_linker_cross_file():
    # File A has a function that calls a function in File B
    decl_a = DeclarationUnit(
        name="handle_login",
        kind="function",
        file_path="src/handlers/auth.py",
        start_line=10,
        end_line=25,
        signature="def handle_login(req):",
        calls=["verify_jwt", "db_find_user"],
    )

    # File B defines verify_jwt
    decl_b = DeclarationUnit(
        name="verify_jwt",
        kind="function",
        file_path="src/security/jwt.py",
        start_line=5,
        end_line=20,
        signature="def verify_jwt(token: str):",
        calls=["decode"],
    )

    # File C is an irrelevant file with no matching calls or tokens
    candidate_files = [
        "src/handlers/auth.py",
        "src/security/jwt.py",
        "assets/styles/theme.css",
    ]

    report = RelationshipLinker.trace_relationships(
        declarations=[decl_a, decl_b],
        all_candidate_files=candidate_files,
        query_tokens=["login", "jwt"],
    )

    # Should link handle_login -> verify_jwt across files
    assert len(report.links) == 1
    link = report.links[0]
    assert link.caller_unit == "handle_login"
    assert link.source_file == "src/handlers/auth.py"
    assert link.target_symbol == "verify_jwt"
    assert link.target_file == "src/security/jwt.py"

    # Donor file should include jwt.py
    assert "src/security/jwt.py" in report.donor_files

    # theme.css should be retracted as a false positive
    assert "assets/styles/theme.css" in report.retracted_files

    # Verify summary and to_dict
    summary = report.format_summary()
    assert "Cross-File Relationships" in summary
    assert "Retracted (False Positive) Files" in summary

    d = report.to_dict()
    assert len(d["links"]) == 1
    assert "donor_files" in d
    assert "retracted_files" in d
