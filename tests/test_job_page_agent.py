"""The progress page only promises the agent when this server runs it."""

from dataclasses import replace

from fastapi.testclient import TestClient

from app.config import get_settings
from app.jobs import create_job
from app.main import app
from app.routes.upload import settings_dep


def page(tmp_path, monkeypatch, agent_on: bool) -> str:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = replace(get_settings(), enable_inspector=agent_on)
    job_id = create_job(settings.jobs_dir).job_id
    app.dependency_overrides[settings_dep] = lambda: settings
    try:
        return TestClient(app).get(f"/jobs/{job_id}").text
    finally:
        app.dependency_overrides.pop(settings_dep, None)


def test_agent_promised_when_on(tmp_path, monkeypatch):
    assert "Watch it work" in page(tmp_path, monkeypatch, True)


def test_agent_not_promised_when_off(tmp_path, monkeypatch):
    text = page(tmp_path, monkeypatch, False)
    assert "Your guide is ready" in text
    assert "Watch it work" not in text
