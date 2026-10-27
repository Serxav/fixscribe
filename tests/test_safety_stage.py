from app import artifacts
from app.domains import profile_for
from app.pipeline.safety_stage import job_texts, run
from app.schemas import Identity, Plan, Safety, Step, Transcript, Turn


def washing_machine(**extra) -> Identity:
    base = {
        "object_name": "front-loading washing machine",
        "category": "appliance",
        "task": "repair",
        "problem": "drum does not spin",
    }
    return Identity(**(base | extra))


def plan(*steps, **extra) -> Plan:
    base = {
        "title": "Clean the pump filter",
        "device": "Washing machine",
        "mode": "silent",
        "duration_s": 60.0,
        "steps": list(steps),
    }
    return Plan(**(base | extra))


def step(index, instruction, **extra) -> Step:
    return Step(
        index=index,
        title=f"s{index}",
        instruction=instruction,
        start_s=10.0 * (index - 1),
        end_s=10.0 * index,
        **extra,
    )


def test_appliance_identity_means_caution_with_domain_prechecks(tmp_path):
    artifacts.save(tmp_path, washing_machine())
    artifacts.save(tmp_path, plan(step(1, "Open the small cover at the bottom.")))
    safety = run(tmp_path, settings=None)
    assert safety.level == "caution"
    assert safety.prechecks == profile_for("appliance").prechecks
    assert "pressurized water" in " ".join(safety.reasons)


def test_gas_pipe_in_step_text_is_professional_only(tmp_path):
    artifacts.save(tmp_path, washing_machine(object_name="dryer", problem=""))
    artifacts.save(tmp_path, plan(step(1, "Disconnect the gas pipe from the back of the dryer.")))
    safety = run(tmp_path, settings=None)
    assert safety.level == "professional_only"
    assert "gas line" in safety.blocked


def test_no_identity_uses_generic_prechecks_and_text_only(tmp_path):
    artifacts.save(tmp_path, plan(step(1, "Tighten the loose leg.")))
    safety = run(tmp_path, settings=None)
    assert safety.level == "normal"
    assert safety.prechecks == profile_for("generic").prechecks


def test_written_file_loads_as_safety(tmp_path):
    artifacts.save(tmp_path, washing_machine())
    artifacts.save(tmp_path, plan(step(1, "Open the small cover at the bottom.")))
    safety = run(tmp_path, settings=None)
    assert artifacts.load(tmp_path, Safety) == safety


def test_job_texts_prefers_turns_over_full_transcript():
    words = job_texts(
        plan(step(1, "Open the cover.", target_part="filter cover", removes=["cover"])),
        Transcript(
            mode="narrated",
            duration_s=60.0,
            transcript="full transcript",
            turns=[Turn(start_s=0, end_s=5, text="first words")],
        ),
    )
    assert "Open the cover." in words
    assert "filter cover" in words
    assert "first words" in words
    assert "full transcript" not in words


def test_job_texts_falls_back_to_transcript_and_none():
    alone = plan(step(1, "Open the cover."))
    assert job_texts(alone, None)[0] == "Clean the pump filter"
    fallback = job_texts(
        alone, Transcript(mode="narrated", duration_s=60.0, transcript="full transcript")
    )
    assert fallback[-1] == "full transcript"
