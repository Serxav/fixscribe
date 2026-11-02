"""Live mode backend and route. Spark is faked, frames are synthetic, no network."""

import io
import json
import types
from dataclasses import replace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from openai import OpenAIError
from PIL import Image

from app import artifacts, meta_client
from app.config import Settings
from app.jobs import create_job
from app.main import app
from app.meta_client import MetaError
from app.pipeline.live import (
    LIVE_JSON_SCHEMA,
    MAX_FRAME_BYTES,
    MAX_SPILL,
    LiveAnswer,
    LiveError,
    LivePart,
    _coach_client,
    _count_call,
    _is_small,
    _spill,
    build_prompt,
    live_marks,
    live_turn,
    manual_name,
    manual_parts,
    marks_stages,
    object_region,
    read_calls,
    save_frame,
    settle_step,
)
from app.routes.upload import settings_dep
from app.schemas import Guide, Safety, Step


def _step(index=1, **overrides):
    base = {
        "index": index,
        "title": f"Step {index}",
        "instruction": f"Do step {index} carefully.",
        "start_s": 0.0,
        "end_s": 10.0,
        "screws": {"count": 2, "boxes": [], "kind": "bolt"},
    }
    base.update(overrides)
    return Step.model_validate(base)


def _guide(steps=2, **overrides):
    base = {
        "title": "Fix the brakes",
        "device": "Bike",
        "mode": "silent",
        "language": "en",
        "duration_s": 60.0,
        "steps": [_step(index) for index in range(1, steps + 1)],
    }
    base.update(overrides)
    return Guide.model_validate(base)


def _frame_bytes(width=320, height=240, exif_orientation=None):
    image = Image.new("RGB", (width, height), (200, 30, 30))
    buf = io.BytesIO()
    if exif_orientation is None:
        image.save(buf, format="JPEG")
    else:
        exif = Image.Exif()
        exif[274] = exif_orientation
        image.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _answer(**overrides):
    base = {
        "step": 1,
        "status": "on_track",
        "say": "Good, keep loosening that bolt.",
        "next": "Turn the bolt counterclockwise.",
        "object_box": {"visible": False, "x_min": 0, "y_min": 0, "x_max": 0, "y_max": 0},
        "confidence": 0.8,
    }
    base.update(overrides)
    return base


class FakeLiveClient:
    """Pipeline-level fake: records the exact respond kwargs, answers fixed JSON."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = 0
        self.respond_kwargs = {}

    def respond(self, **kwargs):
        self.calls += 1
        self.respond_kwargs = kwargs
        return types.SimpleNamespace(output_text=json.dumps(self.answer))


def test_normal_answer_saves_frame_and_counts_call(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    artifacts.save(tmp_path, _guide())
    fake = FakeLiveClient(_answer(step=2, status="done_step"))

    answer = live_turn(tmp_path, settings, _frame_bytes(), last_step=1, client=fake)

    assert answer == LiveAnswer.model_validate(
        _answer(step=2, seen=2, status="done_step", object_box=[])
    )
    assert fake.calls == 1
    assert "<<LAST_STEP>>" not in fake.respond_kwargs["input"][0]["content"][0]["text"]
    assert "1. Step 1" in fake.respond_kwargs["input"][0]["content"][0]["text"]
    assert len(fake.respond_kwargs["input"][0]["content"]) == 2  # prompt + the frame
    assert not list((tmp_path / "live").glob("now-*"))  # nothing of the camera stays on the server
    assert read_calls(tmp_path) == 1


def test_step_is_clamped_into_range(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    artifacts.save(tmp_path, _guide(steps=2))

    high = live_turn(tmp_path, settings, _frame_bytes(), client=FakeLiveClient(_answer(step=99)))
    assert high.seen == 2 and high.pending == 2  # clamped, and waiting for a second look

    low = live_turn(tmp_path, settings, _frame_bytes(), client=FakeLiveClient(_answer(step=-4)))
    assert low.step == 0


def test_professional_only_answers_without_spark(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    guide = _guide()
    guide.safety = Safety(level="professional_only", reasons=["Gas lines must stay closed."])
    artifacts.save(tmp_path, guide)
    fake = FakeLiveClient(_answer())

    answer = live_turn(tmp_path, settings, _frame_bytes(), client=fake)

    assert answer.step == 0
    assert answer.status == "unclear"
    assert answer.say == "Gas lines must stay closed."
    assert answer.next == ""
    assert answer.object_box == []
    assert answer.confidence == 1
    assert fake.calls == 0
    assert not list((tmp_path / "live").glob("now-*"))


def test_too_big_and_bad_frames(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    artifacts.save(tmp_path, _guide())
    fake = FakeLiveClient(_answer())

    with pytest.raises(LiveError, match="too big"):
        live_turn(tmp_path, settings, b"x" * (MAX_FRAME_BYTES + 1), client=fake)
    with pytest.raises(LiveError, match="empty"):
        live_turn(tmp_path, settings, b"", client=fake)
    with pytest.raises(LiveError, match="could not read"):
        live_turn(tmp_path, settings, b"not an image", client=fake)
    assert fake.calls == 0


def test_limit_refuses_without_calling_spark(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    artifacts.save(tmp_path, _guide())
    (tmp_path / "live").mkdir(parents=True, exist_ok=True)
    (tmp_path / "live" / "calls.txt").write_text(f"{Settings().live_max_calls}\n")
    fake = FakeLiveClient(_answer())

    with pytest.raises(LiveError, match="live limit"):
        live_turn(tmp_path, settings, _frame_bytes(), client=fake)

    assert fake.calls == 0


def test_exif_rotated_jpeg_is_accepted(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    artifacts.save(tmp_path, _guide())
    stored = Image.new("RGB", (40, 20), (10, 20, 30)).transpose(Image.Transpose.ROTATE_90)
    exif = Image.Exif()
    exif[274] = 6  # phones store portrait photos rotated, with this tag to fix them
    buf = io.BytesIO()
    stored.save(buf, format="JPEG", exif=exif)

    answer = live_turn(tmp_path, settings, buf.getvalue(), client=FakeLiveClient(_answer()))

    assert answer.step == 1
    with Image.open(save_frame(tmp_path, buf.getvalue())) as saved:
        assert saved.size == (40, 20)


def test_a_big_frame_is_made_smaller(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (2000, 1000)).save(buf, format="JPEG")
    with Image.open(save_frame(tmp_path, buf.getvalue())) as saved:
        assert max(saved.size) <= 1280


def test_a_guide_that_is_not_the_sample_has_a_smaller_coach_limit(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path, live_max_calls=10000)
    (tmp_path / "live").mkdir()
    (tmp_path / "live" / "calls.txt").write_text("1000\n")
    with pytest.raises(LiveError, match="1000 calls"):
        _count_call(tmp_path, settings)
    sample = replace(settings, demo_job=tmp_path.name)
    assert _count_call(tmp_path, sample) == 1000


def test_prompt_lists_steps_and_last_step(tmp_path):
    prompt = build_prompt(_guide(steps=2), last_step=1)

    assert "1. Step 1 — Do step 1 carefully. — 2 bolt — part: " in prompt
    assert "2. Step 2 — Do step 2 carefully. — 2 bolt — part: " in prompt
    assert "step 1" in prompt  # the last step the user was on
    assert "<<STEPS>>" not in prompt and "<<LANGUAGE>>" not in prompt


def test_schema_is_strict():
    assert set(LIVE_JSON_SCHEMA["required"]) == set(LiveAnswer.model_fields) - {"seen", "pending"}
    assert LIVE_JSON_SCHEMA["additionalProperties"] is False


@pytest.fixture()
def jobs_tmp(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    fake = FakeLiveClient(_answer())
    monkeypatch.setattr(meta_client, "_factory", lambda *args, **kwargs: fake)
    app.dependency_overrides[settings_dep] = lambda: Settings(model_api_key="", data_dir=data_dir)
    yield (data_dir / "jobs", fake)
    app.dependency_overrides.pop(settings_dep, None)


def _route_job(jobs_dir, steps=2, **guide_overrides):
    status = create_job(jobs_dir)
    artifacts.save(jobs_dir / status.job_id, _guide(steps=steps, **guide_overrides))
    return status.job_id


def test_route_returns_answer_as_json(jobs_tmp):
    jobs_dir, fake = jobs_tmp
    job_id = _route_job(jobs_dir)
    fake.answer = _answer(step=2, status="done_step", say="Good, that bolt is out.")

    response = TestClient(app).post(
        f"/api/live/{job_id}",
        files={"frame": ("frame.jpg", _frame_bytes(), "image/jpeg")},
        data={"last_step": "1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["step"] == 2
    assert body["status"] == "done_step"
    assert body["say"] == "Good, that bolt is out."
    assert fake.calls == 1


def test_route_limit_is_429(jobs_tmp):
    jobs_dir, fake = jobs_tmp
    job_id = _route_job(jobs_dir)
    live_dir = jobs_dir / job_id / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    (live_dir / "calls.txt").write_text(f"{Settings().live_max_calls}\n")

    response = TestClient(app).post(
        f"/api/live/{job_id}",
        files={"frame": ("frame.jpg", _frame_bytes(), "image/jpeg")},
    )

    assert response.status_code == 429
    assert "live limit" in response.json()["error"]
    assert fake.calls == 0


def test_route_too_big_frame_is_400(jobs_tmp):
    jobs_dir, fake = jobs_tmp
    job_id = _route_job(jobs_dir)

    response = TestClient(app).post(
        f"/api/live/{job_id}",
        files={"frame": ("frame.jpg", b"x" * (MAX_FRAME_BYTES + 1), "image/jpeg")},
    )

    assert response.status_code == 400
    assert "too big" in response.json()["error"]
    assert fake.calls == 0


def test_route_bad_job_and_missing_guide_are_404(jobs_tmp):
    jobs_dir, fake = jobs_tmp
    client = TestClient(app)

    response = client.post(
        "/api/live/nothere",
        files={"frame": ("frame.jpg", _frame_bytes(), "image/jpeg")},
    )
    assert response.status_code == 404

    job_id = _route_job(jobs_dir)
    (jobs_dir / job_id / "guide.json").unlink()
    response = client.post(
        f"/api/live/{job_id}",
        files={"frame": ("frame.jpg", _frame_bytes(), "image/jpeg")},
    )
    assert response.status_code == 404
    assert fake.calls == 0


def test_one_odd_frame_never_moves_the_coach():
    assert settle_step(3, 0, 8, 0.9) == (3, 8)  # far away: wait for a second frame
    assert settle_step(3, 8, 8, 0.2) == (8, 0)  # two in a row
    assert settle_step(3, 8, 5, 0.9) == (3, 5)  # they disagree: start again
    assert settle_step(3, 0, 4, 0.9) == (4, 0)  # a sure next step
    assert settle_step(3, 0, 4, 0.5) == (3, 4)  # an unsure next step
    assert settle_step(0, 0, 1, 0.1) == (1, 0)  # starting at the start needs no second look
    assert settle_step(0, 0, 6, 0.9) == (0, 6)  # starting anywhere else does
    assert settle_step(3, 8, 0, 0.0) == (3, 8)  # a look away keeps the step and what waits
    assert settle_step(3, 0, 4, 0.9, 0) == (3, 4)  # just arrived: sure is not enough yet
    assert settle_step(3, 8, 3, 0.5) == (3, 0)


def test_waiting_step_keeps_the_voice_quiet(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    artifacts.save(tmp_path, _guide(steps=4))
    fake = FakeLiveClient(_answer(step=4, confidence=0.9, say="Now step four."))

    answer = live_turn(tmp_path, settings, _frame_bytes(), last_step=1, client=fake)

    assert (answer.step, answer.seen, answer.pending) == (1, 4, 4)
    assert answer.status == "unclear" and answer.say == "" and answer.next == ""


def test_guide_photos_follow_the_frame(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    guide = _guide(steps=3)
    (tmp_path / "steps").mkdir()
    for step in guide.steps:
        step.image = f"steps/{step.index:02d}.jpg"
        (tmp_path / step.image).write_bytes(_frame_bytes())
    artifacts.save(tmp_path, guide)
    fake = FakeLiveClient(_answer(step=2))

    live_turn(tmp_path, settings, _frame_bytes(), last_step=2, client=fake)

    content = fake.respond_kwargs["input"][0]["content"]
    assert len(content) == 5  # prompt, the camera first, then the photos of steps 1, 2 and 3
    assert "step 1, step 2, step 3" in content[0]["text"]
    assert fake.respond_kwargs["max_output_tokens"] >= 12000


class FakeMarksClient(FakeLiveClient):
    """Grounds two parts, SAM cuts both, the check confirms only the first."""

    def __init__(self, error=None):
        super().__init__({"tiles": [{"n": 1, "real": True, "why": ""}]})
        self.error = error
        self.ground_query = ""

    def ground(self, path, query, *, context="", max_boxes=8, effort="medium"):
        self.ground_query = self.ground_query or query  # the first pointing, not the spare
        self.ground_queries = [*getattr(self, "ground_queries", []), query]
        if self.error:
            raise self.error
        return [
            types.SimpleNamespace(label="back cover", box=(100, 100, 500, 500)),
            types.SimpleNamespace(label="sticker", box=(600, 600, 900, 900)),
        ]

    def segment_boxes(self, path, boxes):
        def found(number, x):
            return types.SimpleNamespace(
                object_id=number,
                confidence=0.9,
                mask=bytes([1] * 100 * 100),
                mask_size=(100, 100),
                mask_bounds=(x, 24, x + 128, 120),
                box=(x, 24, x + 128, 120),
            )

        return [found("1", 32), found("2", 170)], (320, 240)


def _with_target(tmp_path):
    guide = _guide()
    guide.steps[0].target_part = "back cover"
    artifacts.save(tmp_path, guide)
    return Settings(model_api_key="", data_dir=tmp_path)


def test_marks_keep_only_what_the_check_confirms_and_map_back_to_the_frame(tmp_path):
    settings = _with_target(tmp_path)
    fake = FakeMarksClient()

    parts = live_marks(tmp_path, settings, _frame_bytes(), 1, [500, 500, 1000, 1000], fake)

    assert [p.label for p in parts] == ["back cover"]
    assert parts[0].target is True
    assert all(x >= 400 and y >= 400 for x, y in parts[0].outline)  # the close-up's own corner
    assert "back cover" in fake.ground_query
    assert "leave out everything else" in fake.ground_query
    assert read_calls(tmp_path) == 1


def test_marks_use_only_the_parts_the_manual_has_reached():
    guide = _guide(steps=4)
    for step, part in zip(guide.steps, ["cover", "bracket", "battery", "display"], strict=True):
        step.target_part = part

    assert manual_parts(guide, 1) == ["cover"]
    assert manual_parts(guide, 2) == ["bracket", "cover"]
    assert manual_parts(guide, 0) == ["battery", "bracket", "cover", "display"]


def test_a_mark_takes_the_manual_name_or_is_dropped():
    names = ["back cover", "battery"]

    assert manual_name("Replacement battery", names) == "battery"
    assert manual_name("cover", names) == "back cover"
    assert manual_name("display", names) == ""


def test_a_cut_out_that_runs_outside_its_box_is_measured():
    mask = np.zeros((100, 100), dtype=bool)
    mask[40:60, 40:60] = True

    assert _spill(mask, (400, 400, 600, 600)) == 0
    assert _spill(mask, (400, 400, 500, 500)) > MAX_SPILL


def test_no_key_on_the_server_is_a_clear_message(tmp_path, monkeypatch):
    def no_key(*_, **__):
        raise OpenAIError("missing credentials")

    monkeypatch.setattr("app.pipeline.live.make_client", no_key)

    with pytest.raises(LiveError, match="not set up"):
        _coach_client(tmp_path, Settings(model_api_key="", data_dir=tmp_path))


def test_a_tiny_part_shows_only_if_the_step_works_on_it():
    assert _is_small({"cut_box": [10, 10, 40, 40]})
    assert not _is_small({"cut_box": [10, 10, 200, 40]})


def test_marks_failure_loses_only_the_marks(tmp_path):
    settings = _with_target(tmp_path)

    assert (
        live_marks(tmp_path, settings, _frame_bytes(), 1, [], FakeMarksClient(MetaError("x"))) == []
    )


def test_marks_answer_nothing_on_professional_jobs(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    guide = _guide()
    guide.safety = Safety(level="professional_only", reasons=["Gas."])
    artifacts.save(tmp_path, guide)
    fake = FakeMarksClient()

    assert live_marks(tmp_path, settings, _frame_bytes(), 1, [], fake) == []
    assert fake.ground_query == ""


def test_object_region_is_checked():
    box = {"visible": True, "x_min": 700, "y_min": 100, "x_max": 200, "y_max": 1500}
    assert object_region(box) == [200, 100, 700, 1000]
    assert object_region({**box, "visible": False}) == []
    assert object_region({"visible": True}) == []
    assert object_region({"visible": True, "x_min": 1, "y_min": 1, "x_max": 5, "y_max": 5}) == []


def _post_marks(job_id, **data):
    return TestClient(app).post(
        f"/api/live/{job_id}/marks",
        files={"frame": ("frame.jpg", _frame_bytes(), "image/jpeg")},
        data=data,
    )


def test_marks_route_sends_the_cut_outs_then_the_confirmed(jobs_tmp, monkeypatch):
    jobs_dir, _ = jobs_tmp
    job_id = _route_job(jobs_dir)
    asked = {}
    battery = LivePart(label="battery", box=[1, 2, 3, 4], outline=[[1, 2]], confidence=0.9)

    def fake_stages(folder, settings, data, step, region):
        asked.update(step=step, region=region)
        yield False, [battery]
        yield True, []

    monkeypatch.setattr("app.routes.ask.marks_stages", fake_stages)
    response = _post_marks(job_id, step="2", region="10,20,300,400")

    assert response.status_code == 200
    first, last = [json.loads(line) for line in response.text.splitlines()]
    assert first["checked"] is False and first["parts"][0]["label"] == "battery"
    assert last == {"checked": True, "parts": []}
    assert asked == {"step": 2, "region": [10, 20, 300, 400]}


def test_marks_route_error_before_any_mark_is_a_clear_status(jobs_tmp, monkeypatch):
    jobs_dir, _ = jobs_tmp
    job_id = _route_job(jobs_dir)

    def fake_stages(*_):
        raise LiveError("frame is empty")
        yield

    monkeypatch.setattr("app.routes.ask.marks_stages", fake_stages)
    response = _post_marks(job_id)

    assert response.status_code == 400
    assert response.json()["error"] == "frame is empty"


def test_marks_route_error_after_the_cut_outs_clears_them(jobs_tmp, monkeypatch):
    jobs_dir, _ = jobs_tmp
    job_id = _route_job(jobs_dir)
    battery = LivePart(label="battery", box=[1, 2, 3, 4], outline=[[1, 2]], confidence=0.9)

    def fake_stages(*_):
        yield False, [battery]
        raise LiveError("spend limit")

    monkeypatch.setattr("app.routes.ask.marks_stages", fake_stages)
    last = json.loads(_post_marks(job_id).text.splitlines()[-1])

    assert last == {"checked": True, "parts": [], "error": "spend limit"}


def test_stages_show_the_cut_outs_before_the_check(tmp_path):
    settings = _with_target(tmp_path)

    stages = list(marks_stages(tmp_path, settings, _frame_bytes(), 1, [], FakeMarksClient()))

    assert [checked for checked, _ in stages] == [False, True]
    assert [p.label for p in stages[0][1]] == ["back cover"]  # "sticker" is not in the manual
    assert [p.label for p in stages[1][1]] == ["back cover"]


def test_coach_has_its_own_budget(tmp_path, monkeypatch):
    settings = Settings(
        model_api_key="", data_dir=tmp_path, job_budget_usd=1.0, live_budget_usd=0.7
    )
    artifacts.save(tmp_path, _guide())
    seen = {}

    def factory(used, job_dir=None):
        seen.update(budget=used.job_budget_usd, folder=job_dir)
        return FakeLiveClient(_answer())

    monkeypatch.setattr("app.pipeline.live.make_client", factory)
    live_turn(tmp_path, settings, _frame_bytes(), last_step=1)

    assert seen == {"budget": 0.7, "folder": tmp_path / "live"}


class MissesTheTarget(FakeMarksClient):
    """Points only at the back cover first; asked for the battery alone, finds it."""

    def __init__(self):
        super().__init__()
        self.queries = []

    def ground(self, path, query, *, context="", max_boxes=8, effort="medium"):
        self.queries.append(query)
        if query == "the battery":
            return [types.SimpleNamespace(label="battery", box=(100, 100, 500, 500))]
        return [types.SimpleNamespace(label="back cover", box=(600, 600, 900, 900))]


def test_a_step_part_nobody_pointed_at_is_looked_for_again(tmp_path):
    guide = _guide()
    guide.steps[0].target_part = "back cover"
    guide.steps[1].target_part = "battery"
    artifacts.save(tmp_path, guide)
    settings = Settings(model_api_key="", data_dir=tmp_path)
    fake = MissesTheTarget()

    stages = list(marks_stages(tmp_path, settings, _frame_bytes(), 2, [], fake))

    assert fake.queries[-1] == "the battery"  # looked for again, once
    assert len(fake.queries) == 2
    final = stages[-1][1]
    assert any(p.label == "battery" and p.target for p in final)


class RejectsFirstCheck(FakeMarksClient):
    """The first check turns every mark down; the check of the second look confirms it."""

    def __init__(self):
        super().__init__()
        self.checks = 0

    def respond(self, **kwargs):
        self.checks += 1
        real = self.checks > 1
        tiles = [{"n": n, "real": real, "why": ""} for n in (1, 2)]
        return types.SimpleNamespace(output_text=json.dumps({"tiles": tiles}))


def test_a_marked_part_the_check_turns_down_uses_the_spare_second_look(tmp_path):
    settings = _with_target(tmp_path)
    fake = RejectsFirstCheck()

    stages = list(marks_stages(tmp_path, settings, _frame_bytes(), 1, [], fake))

    assert fake.ground_queries[1] == "the back cover"  # pointed at again while the check ran
    assert fake.checks == 2
    final = stages[-1][1]
    assert [p.label for p in final] == ["back cover"] and final[0].target


def test_a_confirmed_part_never_waits_for_the_spare(tmp_path):
    settings = _with_target(tmp_path)
    fake = FakeMarksClient()

    stages = list(marks_stages(tmp_path, settings, _frame_bytes(), 1, [], fake))

    assert fake.calls == 1  # one check; the spare's cut-out is never checked
    assert [p.label for p in stages[-1][1]] == ["back cover"]
