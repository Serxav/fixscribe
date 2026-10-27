"""Domain profiles: every file loads, the fallback never fails, bad files name themselves."""

import json
from pathlib import Path

import pytest

from app.domains import DOMAINS_DIR, DomainError, all_profiles, load_profile, profile_for
from app.schemas import CATEGORIES


def _valid_payload() -> dict:
    return json.loads((DOMAINS_DIR / "generic.json").read_text(encoding="utf-8"))


def _write(tmp_path: Path, name: str, payload: object | str) -> Path:
    path = tmp_path / name
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return path


def test_every_domain_file_loads_and_covers_categories():
    for path in DOMAINS_DIR.glob("*.json"):
        assert load_profile(path).category == path.stem
    profiles = all_profiles()
    assert "generic" in profiles
    for category in CATEGORIES:
        if category != "other":
            assert category in profiles, f"missing profile for {category}"


def test_profile_for_falls_back_to_generic():
    assert profile_for("appliance").category == "appliance"
    assert profile_for(None).category == "generic"
    assert profile_for("other").category == "generic"
    assert profile_for("spaceship").category == "generic"


@pytest.mark.parametrize("mutate", ["hazard", "extra", "stem", "json"])
def test_bad_file_raises_domain_error_naming_the_file(tmp_path, mutate):
    if mutate == "hazard":
        payload = _valid_payload() | {"default_hazards": ["no_such_hazard"]}
        path = _write(tmp_path, "generic.json", payload)
    elif mutate == "extra":
        payload = _valid_payload() | {"no_such_field": 1}
        path = _write(tmp_path, "generic.json", payload)
    elif mutate == "stem":
        path = _write(tmp_path, "mismatch.json", _valid_payload())
    else:
        path = _write(tmp_path, "broken.json", "{not json")
    with pytest.raises(DomainError) as excinfo:
        load_profile(path)
    assert path.name in str(excinfo.value)


def test_automotive_defaults():
    profile = profile_for("automotive")
    assert profile.fasteners[0] == "bolt"
    joined = " ".join(profile.prechecks).lower()
    assert "chock" in joined or "jack" in joined
