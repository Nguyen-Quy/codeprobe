from codeprobe.core.synthesizer import StateSynthesizer
from codeprobe.schemas import DecisionRequest, TaskCategory


def test_extract_file_paths():
    rg_output = """
    src/codeprobe/cli.py:12:def main():
    ./src/codeprobe/executor.py:45:class Investigator:
    tests/test_schemas.py:1:import json
    .git/config:1:something
    __pycache__/foo.pyc:1:binary
    """
    paths = StateSynthesizer.extract_file_paths(rg_output)
    assert "src/codeprobe/cli.py" in paths
    assert "src/codeprobe/executor.py" in paths
    assert "tests/test_schemas.py" in paths
    assert not any(".git" in p or "__pycache__" in p for p in paths)


def test_synthesize_prompt():
    req = DecisionRequest(
        user_goal="Investigate memory leak in cache backend",
        task_category=TaskCategory.INVESTIGATION,
        collected_evidence=["=== SEARCH: cache ===\nsrc/cache.py:10:class Cache:"],
        last_error="MemoryError: out of memory",
        active_file="src/cache.py",
    )
    prompt = StateSynthesizer.synthesize_prompt(req)
    assert "GOAL: Investigate memory leak in cache backend" in prompt
    assert "TASK CATEGORY: investigation" in prompt
    assert "LAST ERROR / EXCEPTION:" in prompt
    assert "MemoryError: out of memory" in prompt
    assert "src/cache.py" in prompt
