import pytest
from fastapi.testclient import TestClient

from codeprobe.server.http import create_http_app


@pytest.fixture
def client():
    app = create_http_app()
    return TestClient(app)


def test_http_health_check(client):
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "codeprobe"
    assert data["version"] == "0.2.0"


def test_http_route_decision(client):
    payload = {
        "user_goal": "Investigate memory leak in worker",
        "task_category": "investigation",
        "collected_evidence": [],
        "known_files": [],
        "budget_remaining_steps": 5,
    }
    response = client.post("/v1/route", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "strategy" in data
    assert "confidence" in data
    assert "recommended_actions" in data
    assert "suggested_model_tier" in data
    assert isinstance(data["recommended_actions"], list)


def test_http_evaluate_evidence(client):
    payload = {
        "user_goal": "Fix crash on startup",
        "task_category": "debugging",
        "collected_evidence": [
            "=== TRACE ===\nFile main.py line 10\nIndexError: list index out of range",
            "=== FILE ===\nmain.py lines 1-20",
            "=== TEST ===\nReproduction test passing",
        ],
        "known_files": ["main.py"],
        "budget_remaining_steps": 4,
    }
    response = client.post("/v1/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "is_sufficient" in data
    assert "strategy" in data
    assert "confidence" in data
