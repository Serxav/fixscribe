"""Illustrate stage tests. The image model is always a fake, never the network."""

from pathlib import Path

from app import artifacts
from app.config import Settings
from app.meta_client import BudgetExceeded, ImagePolicyError
from app.pipeline import illustrate
from app.pipeline.illustrate import Illustrations, build_prompt, select_steps, wants_illustration
from app.schemas import Frames, Identity, Plan, ScrewMap, Step, StepMedia


def make_settings(data_dir: Path) -> Settings:
    return Settings(model_api_key="test-key", data_dir=data_dir, budget_usd=120.0)


def make_step(index: int, **kwargs) -> Step:
    base: dict = {
        "index": index,
        "title": f"step {index}",
        "instruction": f"do step {index}",
        "start_s": float((index - 1) * 10),
        "end_s": float((index - 1) * 10 + 8),
    }
    base.update(kwargs)
    return Step(**base)


class FakeImages:
    """Fake image client: edit_image returns canned bytes or raises."""

    def __init__(self, results):
        self.results = list(results)
        self.calls: list = []

    def edit_image(self, image_path, prompt):
        self.calls.append((Path(image_path), prompt))
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_job(job_dir: Path, steps: list[Step], with_frames: bool = True) -> None:
    plan = Plan(title="fix phone", device="Phone", mode="silent", duration_s=100.0, steps=steps)
    artifacts.save(job_dir, plan)
    identity = Identity(object_name="Phone 12", category="electronics", task="repair")
    artifacts.save(job_dir, identity)
    if with_frames:
        media = [
            StepMedia(index=step.index, keyframe_s=step.start_s, image=step.image)
            for step in steps
            if step.image
        ]
        artifacts.save(job_dir, Frames(steps=media))
    for step in steps:
        if step.image:
            path = job_dir / step.image
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake-jpeg")


def test_wants_illustration_needs_target_part():
    assert not wants_illustration(make_step(1, action="remove"))
    assert not wants_illustration(make_step(1, target_part="  ", action="remove"))
    assert wants_illustration(make_step(1, target_part="back panel", action="remove"))
    assert wants_illustration(
        make_step(1, target_part="back panel", screws=ScrewMap(count=2, kind="screw"))
    )
    assert not wants_illustration(make_step(1, target_part="screen", action="inspect"))
    assert wants_illustration(make_step(1, target_part="cable", action="Disconnect"))


def test_select_steps_keeps_order_and_caps_at_four():
    steps = [
        make_step(1, target_part="panel", action="unscrew"),
        make_step(2, target_part="battery", action="pry"),
        make_step(3, title="talk", instruction="say hi"),  # no part: skipped
        make_step(4, target_part="cable", action="disconnect"),
        make_step(5, target_part="cover", action="open"),
        make_step(6, target_part="bracket", action="unclip"),
    ]
    chosen = select_steps(steps)
    assert [step.index for step in chosen] == [1, 2, 4, 5]
    assert len(chosen) == illustrate.MAX_ILLUSTRATIONS == 4


def test_build_prompt_fills_placeholders(tmp_path):
    step = make_step(
        1, target_part="back panel", action="unscrew", screws=ScrewMap(count=4, kind="screw")
    )
    prompt = build_prompt("Phone 12", step)
    assert "Phone 12" in prompt
    assert "back panel" in prompt
    assert "4 screws" in prompt
    assert "unscrew" in prompt
    assert "<<" not in prompt


def test_build_prompt_without_fasteners(tmp_path):
    step = make_step(1, target_part="cable", action="disconnect")
    prompt = build_prompt("Phone 12", step)
    assert "none" in prompt
    assert "<<" not in prompt


def test_run_writes_webp_and_json(tmp_path):
    job_dir = tmp_path / "job"
    steps = [
        make_step(
            1,
            target_part="back panel",
            action="unscrew",
            screws=ScrewMap(count=2, kind="screw"),
            image="steps/01.jpg",
        ),
        make_step(2, target_part="battery", action="pry", image="steps/02.jpg"),
        make_step(3, title="talk", instruction="say hi", image="steps/03.jpg"),
    ]
    make_job(job_dir, steps)
    fake = FakeImages([b"webp-1", b"webp-2"])

    result = illustrate.run(job_dir, make_settings(tmp_path), client=fake)

    assert isinstance(result, Illustrations)
    assert [item.index for item in result.steps] == [1, 2]
    assert result.steps[0].image == "steps/01_illustration.webp"
    assert (job_dir / "steps" / "01_illustration.webp").read_bytes() == b"webp-1"
    assert (job_dir / "steps" / "02_illustration.webp").read_bytes() == b"webp-2"
    assert len(fake.calls) == 2
    assert fake.calls[0][0] == job_dir / "steps" / "01.jpg"
    assert "back panel" in fake.calls[0][1]
    saved = Illustrations.model_validate_json(
        (job_dir / "illustrations.json").read_text(encoding="utf-8")
    )
    assert [item.index for item in saved.steps] == [1, 2]
    assert saved.notes == []


def test_run_policy_block_skipped_with_note(tmp_path):
    job_dir = tmp_path / "job"
    steps = [
        make_step(1, target_part="panel", action="remove", image="steps/01.jpg"),
        make_step(2, target_part="battery", action="pry", image="steps/02.jpg"),
    ]
    make_job(job_dir, steps)
    fake = FakeImages([ImagePolicyError("refused", status_code=400), b"webp-2"])

    result = illustrate.run(job_dir, make_settings(tmp_path), client=fake)

    assert [item.index for item in result.steps] == [2]
    assert not (job_dir / "steps" / "01_illustration.webp").exists()
    assert any("step 1" in note and "policy" in note for note in result.notes)


def test_run_budget_stop(tmp_path):
    job_dir = tmp_path / "job"
    steps = [
        make_step(1, target_part="panel", action="remove", image="steps/01.jpg"),
        make_step(2, target_part="battery", action="pry", image="steps/02.jpg"),
    ]
    make_job(job_dir, steps)
    fake = FakeImages([BudgetExceeded("broke"), b"webp-2"])

    result = illustrate.run(job_dir, make_settings(tmp_path), client=fake)

    assert result.steps == []
    assert len(fake.calls) == 1
    assert any("budget" in note for note in result.notes)


def test_run_missing_image_skipped_with_note(tmp_path):
    job_dir = tmp_path / "job"
    steps = [
        make_step(1, target_part="panel", action="remove", image="steps/01.jpg"),
        make_step(2, target_part="battery", action="pry"),  # no image at all
    ]
    make_job(job_dir, steps)
    (job_dir / "steps" / "01.jpg").unlink()  # keyframe file gone
    fake = FakeImages([b"webp-1"])

    result = illustrate.run(job_dir, make_settings(tmp_path), client=fake)

    assert result.steps == []
    assert fake.calls == []
    assert len(result.notes) == 2
    assert all("step" in note for note in result.notes)
