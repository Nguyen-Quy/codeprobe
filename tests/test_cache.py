from __future__ import annotations

from pathlib import Path

from codeprobe.cache import LocalEvidenceCache


def test_local_evidence_cache_basic(tmp_path: Path):
    cache = LocalEvidenceCache(tmp_path)
    namespace = "test_ns"
    query = "where is auth handled?"

    # Initially cache miss
    assert cache.get(namespace, query) is None

    # Set cache entry
    sample_payload = {"status": "ok", "candidates": ["src/auth.py"]}
    cache.set(namespace, sample_payload, query)

    # Cache hit
    cached = cache.get(namespace, query)
    assert cached is not None
    assert cached["status"] == "ok"
    assert cached["candidates"] == ["src/auth.py"]

    # Different query misses
    assert cache.get(namespace, "another query") is None

    # Clear cache
    cleared = cache.clear()
    assert cleared >= 1
    assert cache.get(namespace, query) is None
