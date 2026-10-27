"""Narrate stage tests. Everything uses fakes, never the network."""

import json
import types

import pytest

from app import artifacts
from app.config import Settings
from app.pipeline.assembly import build_reassembly
from app.pipeline.narrate import (
    MAX_OUTPUT_TOKENS,
    PROFESSIONAL_LINE,
    NarrateError,
    apply_rules,
    build_prompt,
    cut_words,
    run,
    word_limit,
)
from app.schemas import Identity, Narration, Plan, Safety


def _step(index, start_s, end_s, **overrides):
    base = {
        "index": index,
        "title": f"Step {index}",
        "instruction": f"Do step {index} carefully.",
        "start_s": start_s,
        "end_s": end_s,
    }
    base.update(overrides)
    return base


def _plan(**overrides):
    base = {
        "title": "Fix the fan",
        "device": "Desk fan",
        "mode": "silent",
        "duration_s": 30.0,
        "steps": [
            _step(1, 0.0, 10.0, title="Open the cover", instruction="Lift the cover up."),
            _step(
                2,
                10.0,
                20.0,
                title="Remove the back cover",
                instruction="Take the back cover off.",
                action="unscrew",
                removes=["back cover"],
                screws={"count": 2, "boxes": [], "kind": "screw"},
            ),
        ],
    }
    base.update(overrides)
    return Plan.model_validate(base)


def _identity(**overrides):
    base = {"object_name": "Desk fan", "category": "appliance", "task": "repair"}
    base.update(overrides)
    return Identity.model_validate(base)


class FakeNarrateClient:
    """Pipeline-level fake: records the exact respond kwargs."""

    def __init__(self, answer: str):
        self.answer = answer
        self.respond_kwargs: dict = {}
        self.calls = 0

    def respond(self, **kwargs):
        self.calls += 1
        self.respond_kwargs = kwargs
        return types.SimpleNamespace(output_text=self.answer)


def _answer(**overrides):
    base = {
        "intro": "We fix the desk fan with a screwdriver.",
        "outro_disassemble": "Well done, the fan is open.",
        "outro_assemble": "Well done, the fan is whole again.",
        "steps": [
            {"index": 1, "disassemble": "Lift the cover up.", "assemble": "Put the cover back."},
        ],
    }
    base.update(overrides)
    return base


def test_word_limit_never_below_twelve():
    plan = _plan()
    assert word_limit(plan.steps[0]) == max(12, round(10.0 * 2.6)) == 26
    short = _step(1, 0.0, 1.0)
    assert word_limit(Plan.model_validate({**plan.model_dump(), "steps": [short]}).steps[0]) == 12


def test_cut_words_keeps_short_text():
    assert cut_words("  hello world  ", 12) == "hello world"


def test_missing_step_filled_from_plan_and_reassembly():
    plan = _plan()
    narration = apply_rules(plan, _answer(), "en", None)
    assert [line.index for line in narration.steps] == [1, 2]
    assert narration.steps[0].disassemble == "Lift the cover up."
    assert narration.steps[1].disassemble == "Take the back cover off."
    expected_assemble = next(
        item for item in build_reassembly(plan.steps).steps if item.source_step == 2
    ).instruction
    assert narration.steps[1].assemble == expected_assemble


def test_unknown_index_dropped():
    plan = _plan()
    answer = _answer(
        steps=[
            {"index": 1, "disassemble": "Lift the cover up.", "assemble": "Put it back."},
            {"index": 99, "disassemble": "Something else.", "assemble": "Undo it."},
        ]
    )
    narration = apply_rules(plan, answer, "en", None)
    assert [line.index for line in narration.steps] == [1, 2]


def test_long_line_cut_with_ellipsis():
    plan = _plan(steps=[_step(1, 0.0, 2.0, instruction="Short.")])
    words = [f"word{i}" for i in range(20)]
    answer = _answer(steps=[{"index": 1, "disassemble": " ".join(words), "assemble": "Short."}])
    narration = apply_rules(plan, answer, "en", None)
    assert narration.steps[0].disassemble == " ".join(words[:12]) + "…"
    assert narration.steps[0].disassemble.endswith("…")


def test_professional_only_overrides_every_line():
    plan = _plan()
    safety = Safety(
        level="professional_only", reasons=["Gas risk", "Mains voltage"], prechecks=["Call a pro"]
    )
    narration = apply_rules(plan, _answer(), "en", safety)
    for line in narration.steps:
        assert line.disassemble == PROFESSIONAL_LINE
        assert line.assemble == PROFESSIONAL_LINE
    assert narration.intro == "Gas risk; Mains voltage"


def test_language_defaults_to_en():
    plan = _plan()
    assert apply_rules(plan, _answer(), "es", None).language == "es"
    assert apply_rules(plan, _answer(), "", None).language == "en"


def test_build_prompt_fills_every_placeholder():
    plan = _plan()
    reassembly = build_reassembly(plan.steps)
    prompt = build_prompt(plan, _identity(language="es"), Safety(level="caution"), reassembly)
    assert "<<" not in prompt
    assert "es" in prompt
    assert "Desk fan" in prompt
    assert "1. Open the cover" in prompt
    assert "caution" in prompt


def test_build_prompt_without_identity_or_safety():
    plan = _plan()
    prompt = build_prompt(plan, None, None, build_reassembly(plan.steps))
    assert "<<" not in prompt
    assert "Desk fan" in prompt


def _make_job(tmp_path, plan, identity=None, safety=None):
    job_dir = tmp_path / "job"
    job_dir.mkdir(parents=True, exist_ok=True)
    artifacts.save(job_dir, plan)
    if identity is not None:
        artifacts.save(job_dir, identity)
    if safety is not None:
        artifacts.save(job_dir, safety)
    return job_dir, Settings(model_api_key="", data_dir=tmp_path)


def test_run_writes_narration_and_names_request(tmp_path):
    plan = _plan()
    job_dir, settings = _make_job(tmp_path, plan, _identity(language="es"))
    client = FakeNarrateClient(json.dumps(_answer()))

    result = run(job_dir, settings, client)

    assert isinstance(result, Narration)
    assert artifacts.load(job_dir, Narration) == result
    assert result.language == "es"
    assert client.calls == 1
    assert client.respond_kwargs["text"]["format"]["name"] == "film_narration"
    assert client.respond_kwargs["max_output_tokens"] == MAX_OUTPUT_TOKENS == 12000
    assert (job_dir / "narrate_raw.txt").is_file()


def test_run_invalid_json_raises_but_keeps_raw(tmp_path):
    job_dir, settings = _make_job(tmp_path, _plan())
    client = FakeNarrateClient("not json {{{")

    with pytest.raises(NarrateError, match="Spark returned an invalid narration"):
        run(job_dir, settings, client)

    assert (job_dir / "narrate_raw.txt").read_text(encoding="utf-8") == "not json {{{"
    assert not (job_dir / "narration.json").exists()


def test_run_non_dict_answer_raises(tmp_path):
    job_dir, settings = _make_job(tmp_path, _plan())
    client = FakeNarrateClient(json.dumps(["not", "a", "dict"]))

    with pytest.raises(NarrateError, match="Spark returned an invalid narration"):
        run(job_dir, settings, client)
