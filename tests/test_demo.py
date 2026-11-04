"""The sample guide: copied once, shown on the landing, never changed by a visitor."""

import json

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


def test_several_samples_are_all_seeded_listed_and_read_only(tmp_path):
    source = tmp_path / "demo"
    for name, title in (("one", "First guide"), ("two", "Second guide")):
        (source / name).mkdir(parents=True)
        guide = {"title": title, "steps": [{}, {}], "identity": {"object_name": "laptop"}}
        (source / name / "guide.json").write_text(json.dumps(guide))
    settings = _settings(tmp_path, job=" one , two,one,../x")

    assert demo.sample_ids(settings.demo_job) == ["one", "two"]
    assert demo.seed(settings, source) is True
    assert demo.ready_sample(settings) == "one"
    cards = demo.sample_cards(settings)
    assert [c["title"] for c in cards] == ["First guide", "Second guide"]
    assert cards[1]["steps"] == "2"
    assert demo.is_write_to_sample("POST", "/api/jobs/two/delete", settings.demo_job)
    assert not demo.is_write_to_sample("POST", "/api/live/two", settings.demo_job)
    assert demo.is_sample("two", settings.demo_job)
    assert not demo.is_sample("three", settings.demo_job)


def test_landing_lists_every_sample_guide(tmp_path):
    source = tmp_path / "demo"
    for name in ("one", "two"):
        (source / name).mkdir(parents=True)
        (source / name / "guide.json").write_text(
            json.dumps({"title": f"Guide {name}", "steps": []})
        )
    settings = _settings(tmp_path, job="one,two")
    demo.seed(settings, source)
    app.dependency_overrides[settings_dep] = lambda: settings
    try:
        page = TestClient(app).get("/").text
    finally:
        app.dependency_overrides.pop(settings_dep, None)
    assert 'href="/guides/one/live"' in page
    assert 'href="/guides/two"' in page
    assert "Guide two" in page
