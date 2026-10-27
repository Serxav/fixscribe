# Task 026: analyze and perception use the domain profile
Branch: feat/domain-aware
Owner: Muse Code (muse-spark-1.3, high)

## Goal
Spark's analysis and SAM's fastener search adapt to what `identity.json` says the object is:
a washing machine gets appliance vocabulary and SAM looks for its fastener kind ("bolt" on a car,
"cam lock"... per profile), not always "screw".

## Why this matters for judging
This is where "first detect what it is, then the magic" becomes real for every category.
Use of Meta AI 25 % (Spark + SAM steered by Spark's own identification), Impact 30 %.

## Files to touch
- `app/pipeline/analyze.py`, `prompts/analyze_v1.md`
- `app/pipeline/perception.py`
- `tests/test_analyze.py`, `tests/test_perception.py`

## Do not touch
- `app/schemas.py` (ANALYSIS_JSON_SCHEMA keeps `screw_count`: it now means "fasteners removed"),
  `app/domains.py`, `app/safety.py`, `app/pipeline/runner.py`, `app/pipeline/publish.py`,
  `tests/test_pipeline_full.py`

## What to build
`app/pipeline/analyze.py`:
- `domain_context(identity: Identity | None, profile: DomainProfile) -> str`: a short block:
  ```
  Object: <object_name> (<category>), task: <task>, problem: <problem or "not stated">
  Brand/model: <brand model, or "unknown">
  <profile.prompt_hint>
  Typical parts: <comma list of profile.parts>
  Fasteners in this domain: <comma list of profile.fasteners>; count them as `screw_count`.
  ```
  Without identity: only the last three lines (profile is the generic one).
- `build_prompt(..., domain: str)` replaces `<<DOMAIN>>`. `run` loads identity with
  `artifacts.load_optional`, picks `profile_for(identity.category if identity else None)`.
- `prompts/analyze_v1.md`: add a "## What the video shows" section with `<<DOMAIN>>` before the
  rules, and make the rules generic: rule 6 becomes "`screw_count` is the number of fasteners
  (screws, bolts, nuts, clips... see above) taken out in this step"; the action list adds
  `unbolt`? NO — the schema enum is fixed; do not add actions. Replace phone-only examples with
  neutral ones ("Remove the four screws on the back panel."). Keep every other rule.
- Keep the old phone behaviour: a phone identity must still produce a prompt that talks about
  screws (electronics profile lists "screw" first).

`app/pipeline/perception.py`:
- `fastener_concept(job_dir: Path) -> str`: `profile_for(identity.category).fastener_kind` if
  `identity.json` exists, else `"screw"`.
- `run` computes it once and passes it down; the ledger `_segment(..., "screw")` call uses it.
  Notes that say "screw" use the concept word instead (e.g. "Camera moved too much to verify the
  bolts."). Use a simple plural: concept + "s".

## Done when
- `tests/test_analyze.py`: domain block present with an appliance identity (parts and fasteners
  listed); without identity the generic profile is used; the prompt still contains the transcript
  turns and segments as before.
- `tests/test_perception.py`: with an automotive identity.json the fake client receives concept
  "bolt" for the ledger; without identity it receives "screw" (existing tests unchanged).
- `.venv/bin/pytest -q` all pass; `ruff check .` and `ruff format --check .` clean.

## Notes
- No new Meta calls; cost unchanged.
- `from app.domains import profile_for, DomainProfile`.
