"""Per-visitor limits: one visitor cannot eat the credits meant for everyone."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.limits import COACH_CALLS_PER_MINUTE, Limiter, LimitReached, visitor
from app.main import app
from app.routes.upload import settings_dep


class Clock:
    def __init__(self):
        self.now = 1_000_020.0  # the start of a minute

    def __call__(self):
        return self.now


def test_questions_stop_at_the_hourly_limit_and_come_back(tmp_path):
    clock, settings = Clock(), Settings(data_dir=tmp_path, visitor_questions_per_hour=3)
    limiter = Limiter(clock)
    for _ in range(3):
        limiter.claim("1.1.1.1", "question", settings)
    with pytest.raises(LimitReached, match="3 questions an hour"):
        limiter.claim("1.1.1.1", "question", settings)
    limiter.claim("2.2.2.2", "question", settings)  # another visitor is not affected
    clock.now += 3600
    limiter.claim("1.1.1.1", "question", settings)  # an hour later it is back


def test_videos_are_counted_by_the_day(tmp_path):
    clock, settings = Clock(), Settings(data_dir=tmp_path, visitor_videos_per_day=2)
    limiter = Limiter(clock)
    limiter.claim("a", "video", settings)
    clock.now += 3600
    limiter.claim("a", "video", settings)
    clock.now += 3600
    with pytest.raises(LimitReached, match="2 videos"):
        limiter.claim("a", "video", settings)
    clock.now += 24 * 3600
    limiter.claim("a", "video", settings)


def test_the_coach_counts_minutes_of_use_not_frames(tmp_path):
    clock, settings = Clock(), Settings(data_dir=tmp_path, visitor_coach_minutes_per_day=2)
    limiter = Limiter(clock)
    for _ in range(10):  # many frames within one minute are one minute
        limiter.claim("a", "coach", settings)
        clock.now += 3
    clock.now += 60
    limiter.claim("a", "coach", settings)  # the second minute
    limiter.claim("a", "coach", settings)  # still inside it
    clock.now += 60
    with pytest.raises(LimitReached, match="2 minutes a day"):
        limiter.claim("a", "coach", settings)
    clock.now += 24 * 3600
    limiter.claim("a", "coach", settings)


def test_the_coach_refuses_a_script_sending_frames_too_fast(tmp_path):
    settings = Settings(data_dir=tmp_path)
    limiter = Limiter(Clock())
    for _ in range(COACH_CALLS_PER_MINUTE):
        limiter.claim("a", "coach", settings)
    with pytest.raises(LimitReached, match="Too many frames"):
        limiter.claim("a", "coach", settings)


def test_zero_turns_a_limit_off(tmp_path):
    settings = Settings(data_dir=tmp_path, visitor_actions_per_hour=0)
    limiter = Limiter(Clock())
    for _ in range(500):
        limiter.claim("a", "action", settings)


class FakeRequest:
    def __init__(self, host, forwarded=""):
        self.client = type("C", (), {"host": host})()
        self.headers = {"x-forwarded-for": forwarded} if forwarded else {}


def test_a_visitor_behind_the_proxy_is_its_last_forwarded_address(tmp_path):
    trusting = Settings(data_dir=tmp_path, trust_proxy=True)
    faked = FakeRequest("10.0.0.1", "6.6.6.6, 203.0.113.9")
    assert visitor(faked, trusting) == "203.0.113.9"  # the first entry can be anything
    assert visitor(faked, Settings(data_dir=tmp_path)) == "10.0.0.1"  # no proxy: never trusted
    assert visitor(FakeRequest("10.0.0.1"), trusting) == "10.0.0.1"


@pytest.fixture
def strict(tmp_path):
    settings = Settings(
        model_api_key="",
        data_dir=tmp_path,
        visitor_questions_per_hour=1,
        visitor_videos_per_day=1,
        visitor_actions_per_hour=1,
    )
    app.dependency_overrides[settings_dep] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.pop(settings_dep, None)


def test_a_route_over_the_limit_answers_429_with_a_sentence(strict):
    first = strict.post("/api/live/nojob/ask", data={"text": "which screw"})
    assert first.status_code != 429  # counted, then refused for its own reason
    second = strict.post("/api/live/nojob/ask", data={"text": "which screw"})
    assert second.status_code == 429
    assert second.json() == {"error": "You can ask 1 questions an hour. Try again later."}
    hear = strict.post("/api/live/nojob/hear", files={"audio": ("a.wav", b"x", "audio/wav")})
    assert hear.status_code == 429  # voice and typed questions share one count


def test_every_route_that_spends_credits_is_limited():
    from app.routes import ask, checks, console, export, guides, jobs, taps, tray, upload

    limited = set()
    modules = (ask, checks, console, export, guides, jobs, taps, tray, upload)
    for route in (route for module in modules for route in module.router.routes):
        calls = [d.dependency.__qualname__ for d in getattr(route, "dependencies", [])]
        if any(name.startswith("limit.") for name in calls):
            limited.add(route.path)
    assert limited == {
        "/upload",
        "/api/live/{job_id}",
        "/api/live/{job_id}/marks",
        "/api/live/{job_id}/hear",
        "/api/live/{job_id}/ask",
        "/api/voice/{job_id}",
        "/guides/{job_id}/steps/{index}/check",
        "/guides/{job_id}/steps/{index}/fasteners",
        "/guides/{job_id}/steps/{index}/fasteners/{number}/remove",
        "/api/jobs/{job_id}/agent/start",
        "/api/jobs/{job_id}/agent/resume",
        "/api/jobs/{job_id}/agent/answer",
        "/api/jobs/{job_id}/resume",
    }


def test_an_upload_over_the_limit_shows_a_page(strict, monkeypatch):
    monkeypatch.setattr("app.routes.upload.start_job", lambda *a, **k: None)
    files = {"video": ("repair.mp4", b"0123", "video/mp4")}
    strict.post("/upload", files=files, follow_redirects=False)
    again = strict.post("/upload", files=files, follow_redirects=False)
    assert again.status_code == 429
    assert "1 videos into guides a day" in again.text
