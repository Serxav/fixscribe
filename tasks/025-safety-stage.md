# Task 025: safety stage + publish carries identity, safety and fastener kind
Branch: feat/safety-stage
Owner: Muse Code (muse-spark-1.3, high)

## Goal
A `safety` pipeline stage that writes `safety.json` with the rules in `app/safety.py`, and a
`publish` that puts identity and safety in the guide and refuses to give instructions for
professional-only jobs.

## Why this matters for judging
Universal repair is only credible if it is safe: a gas boiler or an airbag must never get a
DIY guide. Impact 30 % (trust), Technical depth 20 % (rules first, model can only be stricter).

## Files to touch
- `app/pipeline/safety_stage.py` (new)
- `app/pipeline/publish.py`
- `tests/test_safety_stage.py` (new), `tests/test_publish.py`

## Do not touch
- `app/safety.py`, `app/domains.py`, `app/schemas.py`, `app/pipeline/runner.py`,
  `tests/test_pipeline_full.py` (Claude Code owns them and wires the stage)
- `app/pipeline/analyze.py`, `app/pipeline/perception.py`, `prompts/` (another task edits them now)

## What to build
`app/pipeline/safety_stage.py`:
- `VERSION = "1"`
- `job_texts(plan: Plan, transcript: Transcript | None) -> list[str]`: every word we have:
  plan title, device, summary, warnings, and for each step title, instruction, target_part,
  removes, warnings; plus every transcript turn text (or `transcript.transcript` if no turns).
- `run(job_dir: Path, settings: Any) -> Safety`:
  identity = `artifacts.load_optional(job_dir, Identity)`; plan = `artifacts.load(job_dir, Plan)`;
  transcript optional; profile = `profile_for(identity.category if identity else None)`.
  If identity exists, merge `profile.default_hazards` into its hazards (keep order, no duplicates)
  with `identity.model_copy(update=...)`. Then
  `safety = evaluate(identity, job_texts(...), profile.prechecks)`, save it, return it.
  No Meta call in this stage.

`app/pipeline/publish.py` (bump `VERSION` to "3"):
- `build_guide(plan, frames, perception=None, identity=None, safety=None)`:
  - `guide.identity = identity`, `guide.safety = safety`; `guide.language = identity.language`
    when identity exists.
  - fastener kind: `kind = profile_for(identity.category).fastener_kind` if identity else "screw";
    every `ScrewMap` in the steps (from the plan and from `with_perception`) gets `kind=kind`.
  - `safety.level == "caution"`: `guide.warnings = prechecks + plan.warnings` (no duplicates).
  - `safety.level == "professional_only"`: keep steps (title, image, clip, warnings, times), but
    replace every step `instruction` with `PRO_ONLY_STEP = "A qualified professional must do this
    step. FixScribe does not give instructions for it."`, set `reassembly = []`, and add to
    `checks` one line `PRO_ONLY_CHECK + " " + " ".join(safety.reasons)` where
    `PRO_ONLY_CHECK = "Professional-only job:"`. Warnings also get the prechecks.
  - `normal` or no safety: unchanged behaviour (existing tests must still pass untouched).
- `run` loads Identity and Safety with `load_optional` and passes them.

## Done when
- `tests/test_safety_stage.py`: (1) washing machine identity + a plain plan → level "caution",
  prechecks from the appliance profile, hazards include pressurized_water; (2) plan step text
  "disconnect the gas pipe" → "professional_only", blocked has "gas line"; (3) no identity →
  generic prechecks, level from text only; (4) the file written loads as Safety.
- `tests/test_publish.py` new tests: identity/safety copied into the guide; kind "bolt" for an
  automotive identity on a step with screws; caution puts prechecks first in warnings;
  professional_only replaces instructions, empties reassembly, adds the check; no identity →
  kind stays "screw".
- `.venv/bin/pytest -q` all pass; `ruff check .` and `ruff format --check .` clean.

## Notes
- Read `app/safety.py` and `app/domains.py` first; use `evaluate`, `profile_for` as they are.
- Keep functions short; Sergi must be able to read publish.py.
