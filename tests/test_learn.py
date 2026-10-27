"""Learn stage (profile_suggestions.json) and the profile review script."""

import shutil

import pytest

from app import artifacts
from app.domains import DOMAINS_DIR, load_profile, profile_for
from app.pipeline import learn
from app.schemas import Guide, Identity, ProfileSuggestions, ScrewMap, Step
from scripts.review_profiles import main as review_main


def make_step(index, title, **extra):
    return Step(
        index=index,
        title=title,
        instruction="...",
        start_s=float(index),
        end_s=float(index + 1),
        **extra,
    )


def make_guide(**extra):
    return Guide(title="Fix washer", device="Washer X", mode="narrated", **extra)


def appliance_job(tmp_path, job_id="job1", **guide_extra):
    guide_extra.setdefault("parts", ["drain pump"])
    guide_extra.setdefault(
        "steps", [make_step(1, "Pump out", target_part="drain pump", removes=["drain hose"])]
    )
    job = tmp_path / "jobs" / job_id
    artifacts.save(job, make_guide(**guide_extra))
    artifacts.save(job, Identity(object_name="Washer X", category="appliance", task="repair"))
    return learn.run(job, settings=None)


def test_version_is_1():
    assert learn.VERSION == "1"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("The Drain Pumps ", "drain pump"),
        ("  A Screw ", "screw"),
        ("an O-Ring", "o-ring"),
        ("THE drum", "drum"),
        ("glass", "glass"),  # ends in "ss": no singular
        ("bus", "bus"),  # too short to singularize
        ("nut driver set", "nut driver set"),
    ],
)
def test_normalize_term_examples(raw, expected):
    assert learn.normalize_term(raw) == expected


def test_suggest_skips_known_terms_and_finds_new_part_and_tool():
    profile = profile_for("appliance")
    guide = make_guide(
        parts=["drum", "drain pump", "ax"],
        tools=["pliers", "spudger"],
        steps=[
            make_step(
                1,
                "Remove the drain pump",
                target_part="The Drain Pumps",
                removes=["drum", "drain pump"],
                screws=ScrewMap(count=1, kind="screw"),
            ),
            make_step(2, "Rivet the bracket", screws=ScrewMap(count=1, kind="rivets")),
        ],
    )
    found = learn.suggest(guide, profile)
    by_field = {(item.field, item.value) for item in found}
    assert ("parts", "drain pump") in by_field  # new part
    assert ("tools", "spudger") in by_field  # new tool
    assert ("fasteners", "rivet") in by_field  # new fastener kind
    assert not {(field, value) for field, value in by_field if value in {"drum", "pliers"}}
    assert not {(field, value) for field, value in by_field if value in {"screw", "ax", ""}}
    assert len([item for item in found if item.value == "drain pump"]) == 1  # no duplicates
    assert {item.seen_in for item in found if item.value == "spudger"} == {"guide tools"}
    assert {item.seen_in for item in found if item.value == "rivet"} == {
        "step 2: Rivet the bracket"
    }


def test_run_uses_identity_category_and_saves(tmp_path):
    job = tmp_path / "job1"
    artifacts.save(job, make_guide(parts=["drain pump"]))
    identity = Identity(object_name="Washer X", category="appliance", task="repair")
    artifacts.save(job, identity)
    found = learn.run(job, settings=None)
    assert found.category == "appliance"
    assert found.object_name == "Washer X"
    assert any(item.value == "drain pump" for item in found.suggestions)
    assert artifacts.load(job, ProfileSuggestions) == found


def test_run_without_identity_uses_generic(tmp_path):
    job = tmp_path / "job1"
    artifacts.save(job, make_guide(parts=["cover"]))
    found = learn.run(job, settings=None)
    assert found.category == "generic"
    assert found.object_name == ""


def test_run_with_other_category_uses_generic_but_keeps_name(tmp_path):
    job = tmp_path / "job1"
    artifacts.save(job, make_guide(parts=["cover"]))
    artifacts.save(job, Identity(object_name="Mystery box", category="other", task="repair"))
    found = learn.run(job, settings=None)
    assert found.category == "generic"
    assert found.object_name == "Mystery box"


def test_run_needs_guide_json(tmp_path):
    from app.artifacts import ArtifactError

    with pytest.raises(ArtifactError):
        learn.run(tmp_path / "job1", settings=None)


def copy_domains(tmp_path):
    dest = tmp_path / "domains"
    shutil.copytree(DOMAINS_DIR, dest)
    return dest


def test_apply_adds_terms_and_keeps_file_valid(tmp_path, capsys):
    domains = copy_domains(tmp_path)
    appliance_job(tmp_path, tools=["spudger"])
    jobs = tmp_path / "jobs"
    assert review_main(["apply", "job1", "--domains", str(domains), "--jobs", str(jobs)]) == 0
    profile = load_profile(domains / "appliance.json")
    assert "drain pump" in profile.parts
    assert "spudger" in profile.tools
    out = capsys.readouterr().out
    assert "drain pump" in out


def test_apply_only_limits_fields(tmp_path):
    domains = copy_domains(tmp_path)
    appliance_job(tmp_path, tools=["spudger"])
    jobs = tmp_path / "jobs"
    assert (
        review_main(
            ["apply", "job1", "--only", "parts", "--domains", str(domains), "--jobs", str(jobs)]
        )
        == 0
    )
    profile = load_profile(domains / "appliance.json")
    assert "drain pump" in profile.parts
    assert "spudger" not in profile.tools


def test_apply_respects_limits_and_reports_skipped(tmp_path, capsys):
    domains = copy_domains(tmp_path)
    appliance_job(tmp_path, parts=[f"widget {n}" for n in range(15)])
    jobs = tmp_path / "jobs"
    assert review_main(["apply", "job1", "--domains", str(domains), "--jobs", str(jobs)]) == 0
    profile = load_profile(domains / "appliance.json")
    assert len(profile.parts) == 20
    out = capsys.readouterr().out
    assert "skipped" in out


def test_apply_refuses_generic_without_flag(tmp_path, capsys):
    domains = copy_domains(tmp_path)
    before = (domains / "generic.json").read_text(encoding="utf-8")
    job = tmp_path / "jobs" / "job1"
    artifacts.save(job, make_guide(parts=["thingamajig"]))
    learn.run(job, settings=None)
    jobs = tmp_path / "jobs"
    assert review_main(["apply", "job1", "--domains", str(domains), "--jobs", str(jobs)]) != 0
    assert (domains / "generic.json").read_text(encoding="utf-8") == before
    capsys.readouterr()
    assert (
        review_main(
            ["apply", "job1", "--allow-generic", "--domains", str(domains), "--jobs", str(jobs)]
        )
        == 0
    )
    assert "thingamajig" in load_profile(domains / "generic.json").parts


def test_list_prints_counts(tmp_path, capsys):
    copy_domains(tmp_path)
    appliance_job(tmp_path, "job1", parts=["drain pump"])
    appliance_job(tmp_path, "job2", parts=["drain pump", "widget"])
    assert review_main(["list", "--jobs", str(tmp_path / "jobs")]) == 0
    out = capsys.readouterr().out
    assert "appliance" in out
    assert "drain pump" in out and "2 job(s)" in out
    assert "widget" in out and "1 job(s)" in out


def test_tool_names_are_not_singularized():
    from app.pipeline.learn import normalize_term

    assert normalize_term("Pliers", singular=False) == "pliers"
    assert normalize_term("The Drain Pumps ") == "drain pump"
