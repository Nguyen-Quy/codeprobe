from __future__ import annotations

from codeprobe.core.patcher import PatchApplicator
from codeprobe.schemas import CodeTarget


def test_patch_applicator_syntax_validation(tmp_path):
    applicator = PatchApplicator(tmp_path)

    # Valid Python syntax
    applicator.validate_syntax("test.py", "def valid_foo():\n    return 42\n")

    # Invalid Python syntax must raise ValueError
    try:
        applicator.validate_syntax("test.py", "def invalid_foo(\nreturn 42")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "syntax error" in str(e).lower()


def test_patch_applicator_bracket_validation(tmp_path):
    applicator = PatchApplicator(tmp_path)

    # Valid JS/TS
    applicator.validate_syntax("test.ts", "function foo() { return [1, 2]; }")

    # Unclosed bracket
    try:
        applicator.validate_syntax("test.ts", "function foo() { return [1, 2; }")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "mismatched bracket" in str(e).lower() or "unclosed" in str(e).lower()


def test_patch_apply_and_rollback(tmp_path):
    target_file = tmp_path / "service.py"
    target_file.write_text("class Payment:\n    amount: int = 10\n", encoding="utf-8")

    applicator = PatchApplicator(tmp_path)

    target = CodeTarget(
        file_path="service.py",
        start_line=2,
        end_line=2,
        current_code="    amount: int = 10",
        target_content="    amount: int = 10",
        replacement_content="    amount: int = 20",
    )

    # Dry run does not change file
    dry_res = applicator.apply_target(target, dry_run=True)
    assert dry_res.success is True
    assert "amount: int = 20" in dry_res.diff
    assert "amount: int = 10" in target_file.read_text(encoding="utf-8")

    # Real apply
    apply_res = applicator.apply_target(target, dry_run=False)
    assert apply_res.success is True
    assert "amount: int = 20" in target_file.read_text(encoding="utf-8")
    assert (tmp_path / "service.py.bak").is_file()

    # Rollback restores original
    rollback_res = applicator.rollback("service.py")
    assert rollback_res.success is True
    assert "amount: int = 10" in target_file.read_text(encoding="utf-8")
    assert not (tmp_path / "service.py.bak").exists()
