# Task 024: domain profiles (one data file per repair category)
Branch: feat/domains
Owner: Muse Code (muse-spark-1.3, high)

## Goal
Pluggable domain profiles: one JSON file per category in `domains/`, loaded and validated by
`app/domains.py`. Adding a new category later = adding one JSON file, no code change.

## Why this matters for judging
FixScribe is universal (phones, washing machines, chairs, cars, taps...). Profiles tell SAM what
fasteners to look for (screws vs bolts vs clips vs hose clamps), which tools to list and which
safety pre-checks are mandatory. Impact 30 % and Technical depth 20 % (clean extensibility).

## Files to touch
- `app/domains.py` (new)
- `domains/electronics.json`, `domains/appliance.json`, `domains/furniture.json`,
  `domains/automotive.json`, `domains/plumbing.json`, `domains/electrical.json`,
  `domains/tools.json`, `domains/generic.json` (new)
- `tests/test_domains.py` (new)

## Do not touch
- `app/schemas.py` (read `CATEGORIES` and `HAZARDS` from it, do not change them)
- every pipeline stage, `app/meta_client.py`, every other file

## What to build
In `app/domains.py`:
```python
DOMAINS_DIR = Path(__file__).resolve().parents[1] / "domains"

class DomainProfile(BaseModel):          # model_config = ConfigDict(extra="forbid", frozen=True)
    category: str                        # file stem, e.g. "appliance"; "generic" for the fallback
    label: str                           # "Home appliances"
    fasteners: list[str]                 # SAM concepts, most common first, 2..8 items, lower case
                                         # singular nouns SAM understands: "screw", "bolt", "nut",
                                         # "plastic clip", "hose clamp", "rivet", "cam lock"...
    fastener_kind: str                   # default ScrewMap.kind for this domain: "screw", "bolt"...
    parts: list[str]                     # 5..20 typical part names (vocabulary for prompts)
    tools: list[str]                     # 3..12 common tools
    prechecks: list[str]                 # mandatory safety actions before step 1, imperative,
                                         # each < 100 chars ("Unplug the machine from the wall.")
    default_hazards: list[str]           # each must be in schemas.HAZARDS (validate it)
    prompt_hint: str                     # 1–3 sentences added to the analyze prompt, < 400 chars

def load_profile(path: Path) -> DomainProfile   # raises DomainError naming the file on bad JSON/fields
def all_profiles(domains_dir: Path = DOMAINS_DIR) -> dict[str, DomainProfile]   # cached (functools.cache on the default dir is fine)
def profile_for(category: str | None, domains_dir: Path = DOMAINS_DIR) -> DomainProfile
    # exact category → its profile; None, "other" or unknown → "generic". Never raises for an unknown category.
class DomainError(Exception)
```
Validators: `category` equals the file stem (check in `load_profile`); `fasteners` non-empty,
unique, lower case; every `default_hazards` item in `HAZARDS`; `fastener_kind` in `fasteners`
or equal to its first word (e.g. "screw" for "phillips screw"); keep it simple.

Content (English, practical, written by you — no copied text):
- electronics: phones, laptops, consoles. Fasteners: screw, pentalobe screw, plastic clip, ribbon
  connector latch, adhesive strip. Prechecks: power off, disconnect the battery connector first,
  discharge to < 25 % before opening a lithium battery device. Hazards: lithium_battery, sharp_edges.
- appliance: washing machines, fridges, dishwashers, microwaves. Prechecks: unplug, close the water
  tap, never open a microwave's high-voltage section. Hazards: mains_voltage, pressurized_water,
  heavy_part, sharp_edges.
- furniture: chairs, tables, wardrobes, drawers, doors. Fasteners: screw, cam lock, wooden dowel,
  bolt, hinge. Hazards: heavy_part.
- automotive: Prechecks: engine off and cool, parking brake, chock the wheels, never work under a
  car held only by a jack, disconnect the 12 V battery negative terminal for electrical work.
  Fasteners: bolt, nut, hose clamp, plastic clip, screw. Hazards: raised_vehicle, hot_surface,
  heavy_part, chemicals.
- plumbing: Prechecks: close the water supply, open a tap to release pressure, put a bucket
  under. Fasteners: compression nut, hose clamp, screw, bolt. Hazards: pressurized_water.
- electrical: Prechecks: switch off the circuit breaker, test with a voltage tester before
  touching. Hazards: mains_voltage. Fasteners: terminal screw, screw, wire connector.
- tools: power tools and hand tools. Prechecks: remove the battery / unplug.
- generic: fasteners screw, bolt, nut, clip; prechecks: switch off and unplug any power source;
  no default hazards; neutral prompt_hint.

## Done when
- `.venv/bin/pytest -q tests/test_domains.py` passes with tests for:
  1. every file in `domains/` loads, and every category in `schemas.CATEGORIES` except "other"
     has a profile; "generic" exists.
  2. `profile_for("appliance").category == "appliance"`; `profile_for(None)`, `profile_for("other")`,
     `profile_for("spaceship")` all return "generic".
  3. a bad file (tmp_path: unknown hazard, extra field, stem mismatch, invalid JSON) raises
     DomainError whose message contains the file name.
  4. `profile_for("automotive").fasteners[0] == "bolt"` and its prechecks mention chocks/jack.
- `.venv/bin/pytest -q` (all) passes; `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .`
  are clean.

## Notes
- No Meta calls in this task. No new dependency (pydantic is already there).
- Keep `app/domains.py` under ~120 lines and easy to read.
