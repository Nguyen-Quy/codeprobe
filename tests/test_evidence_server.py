from __future__ import annotations

from codeprobe.core.evidence import EvidenceManager
from codeprobe.core.llm_server import (
    find_llama_server_binary,
    find_model_path,
    get_server_status,
)


def test_evidence_manager_deduplication():
    em = EvidenceManager()
    item1 = em.add("src/app.py", "def run():\n    pass", "source_code", 1, 5, status="FACT")
    item2 = em.add("src/app.py", "def run():\n    pass", "source_code", 1, 5, status="FACT")
    assert item1.content_hash == item2.content_hash
    assert len(em.all_items()) == 1


def test_evidence_manager_skeletonization():
    code = """def complex_function(a, b):
    \"\"\"Docstring explaining logic.\"\"\"
    x = 1
    y = 2
    z = 3
    for i in range(100):
        print(i)
    if x > 0:
        return a + b
    return 0
"""
    skeleton = EvidenceManager.skeletonize_code(code, max_body_lines=5)
    assert "def complex_function(a, b):" in skeleton
    assert "return a + b" in skeleton
    assert "# ... [body pruned for token efficiency]" in skeleton


def test_evidence_manager_export_summary():
    em = EvidenceManager()
    em.add("src/auth.py", "def authenticate(): ...", "source_code", 10, 20, status="FACT")
    em.add("dr_module", "missing replication heartbeat", "command_output", status="GAP")

    summary = em.export_compact_summary()
    assert "Verified Facts" in summary
    assert "src/auth.py:10-20" in summary
    assert "Unresolved Questions" in summary
    assert "missing replication heartbeat" in summary


def test_llm_server_detection():
    bin_path = find_llama_server_binary()
    assert bin_path is not None
    assert "llama-server" in bin_path

    model_p = find_model_path()
    assert model_p is not None
    assert model_p.is_file()

    status = get_server_status()
    assert "alive" in status
    assert status["binary"] is not None
