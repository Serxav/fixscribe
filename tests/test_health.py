from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_answers_head_for_uptime_monitors():
    assert TestClient(app).head("/health").status_code == 200
