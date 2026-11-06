from __future__ import annotations

from unittest.mock import patch

from codeprobe.cache import LocalEvidenceCache
from codeprobe.core.llm_server import detect_optimal_gpu_layers
from codeprobe.executor import Investigator


def test_detect_optimal_gpu_layers():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "2048\n"
        layers = detect_optimal_gpu_layers()
        # 2048 - 400 = 1648 // 52 = 31 -> capped at 28
        assert layers == 28

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        layers = detect_optimal_gpu_layers()
        assert layers == 16


def test_git_commit_aware_cache(tmp_path):
    cache = LocalEvidenceCache(tmp_path)

    # Mock git head
    with patch.object(cache, "get_git_head", return_value="abc1234"):
        payload = {"summary": "Cached answer for payment", "user_goal": "payment query"}
        cache.set_investigation("payment query", "auto", payload)

        fetched = cache.get_investigation("payment query", "auto")
        assert fetched == payload

    # If git commit changes, cache misses
    with patch.object(cache, "get_git_head", return_value="def5678"):
        fetched_new = cache.get_investigation("payment query", "auto")
        assert fetched_new is None


def test_investigator_commit_cache_roundtrip(tmp_path):
    (tmp_path / "app.py").write_text("def hello_world(): return 'hi'", encoding="utf-8")
    investigator = Investigator()

    with patch("codeprobe.cache.LocalEvidenceCache.get_git_head", return_value="commit_hash_111"):
        # First explore populates cache
        res1 = investigator.explore(
            query="Where is hello_world defined?",
            workspace_path=str(tmp_path),
            max_steps=1,
            synthesize_summary=False,
        )
        assert res1 is not None

        # Second explore retrieves from cache instantly
        res2 = investigator.explore(
            query="Where is hello_world defined?",
            workspace_path=str(tmp_path),
            max_steps=1,
            synthesize_summary=False,
        )
        assert res2.investigation_id == res1.investigation_id

