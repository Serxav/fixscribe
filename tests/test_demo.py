"""The sample guide: copied once, shown on the landing, never changed by a visitor."""

from fastapi.testclient import TestClient

from app import demo
from app.config import Settings
from app.main import app
from app.routes.upload import settings_dep


def _settings(tmp_path, job="sample"):
    return Settings(model_api_key="", data_dir=tmp_path / "data", demo_job=job)


def _source(tmp_path):
    origin = tmp_path / "demo" / "sample"
    origin.mkdir(parents=True)
    (origin / "guide.json").write_text("{}")
    return tmp_path / "demo"


def test_seed_copies_once_and_keeps_what_is_there(tmp_path):
    settings = _settings(tmp_path)
    source = _source(tmp_path)

    assert demo.seed(settings, source) is True
    assert demo.ready_sample(settings) == "sample"
    (settings.jobs_dir / "sample" / "guide.json").write_text('{"kept": true}')
    assert demo.seed(settings, source) is False
    assert "kept" in (settings.jobs_dir / "sample" / "guide.json").read_text()


def test_no_sample_when_not_set_or_not_shipped(tmp_path):
    assert demo.seed(_settings(tmp_path, job=""), _source(tmp_path)) is False
    assert demo.seed(_settings(tmp_path, job="other"), _source(tmp_path / "x")) is False
    assert demo.ready_sample(_settings(tmp_path, job="other")) == ""


def test_visitors_can_use_the_sample_but_not_change_it():
    write = demo.is_write_to_sample
    assert write("POST", "/api/jobs/sample/delete", "sample")
    assert write("POST", "/api/jobs/sample/agent/start", "sample")
    assert write("POST", "/guides/sample/steps/1/check", "sample")
    assert not write("GET", "/guides/sample", "sample")
    assert not write("POST", "/api/live/sample", "sample")
    assert not write("POST", "/api/live/sample/marks", "sample")
    assert not write("POST", "/api/voice/sample", "sample")
    assert not write("POST", "/api/jobs/other/delete", "sample")
    assert not write("POST", "/api/jobs/sample/delete", "")


def test_delete_of_the_sample_is_refused_by_the_app(monkeypatch):
    monkeypatch.setenv("DEMO_JOB", "sample")

    response = TestClient(app).post("/api/jobs/sample/delete")

    assert response.status_code == 403


def test_landing_offers_the_sample_only_when_it_exists(tmp_path):
    settings = _settings(tmp_path)
    app.dependency_overrides[settings_dep] = lambda: settings
    try:
        assert "Try the live coach" not in TestClient(app).get("/").text
        demo.seed(settings, _source(tmp_path))
        assert "/guides/sample/live" in TestClient(app).get("/").text
    finally:
        app.dependency_overrides.pop(settings_dep, None)
