# Task 027: proof stage (every claim of the guide with its evidence)
Branch: feat/proof
Owner: Muse Code (muse-spark-1.3, high)

## Goal
A deterministic `proof` stage that writes `proof.json`: for every planned step, each claim
(boundaries, instruction, fastener count, part) with a status verified / supported / unverified
and human-readable sources. Publish puts it in the guide.

## Why this matters for judging
"A guide with no made-up facts, and you can check it": judges tap a claim and see the second of
video, the spoken words or the SAM measurement behind it. Technical depth 20 %, Impact 30 %.

## Files to touch
- `app/pipeline/proof.py` (new), `tests/test_proof.py` (new)
- `app/pipeline/publish.py` (only: load Proof with `artifacts.load_optional`, pass it to
  `build_guide(..., proof=None)` and set `guide.proof`), `tests/test_publish.py` (one test)

## Do not touch
- `app/schemas.py` (Claim, StepProof, Proof already exist: read them), `app/pipeline/runner.py`,
  `tests/test_pipeline_full.py`, every other stage

## What to build
`app/pipeline/proof.py`, `VERSION = "1"`, no Meta call:
- Inputs (all optional except plan): `Plan`, `Fusion`, `Refine`, `Perception`, `Transcript`.
  Read `app/pipeline/plan.py` first to see how plan step indexes relate to fusion/refine
  indexes; match them the same way plan.py does, and write that rule in a comment.
- `boundaries_claim(step, fusion_step, refined) -> Claim`:
  sources: fusion start/end sources other than "spark" ("voice cut at 12.4 s", "pause at ...",
  "scene change at ..."), and refine ("timecode re-check: 12.6–20.1 s") when a refined step with
  confidence >= 0.7 exists. verified = an independent signal (non-spark source) AND refine;
  supported = one of them; unverified = neither.
- `instruction_claim(step, transcript) -> Claim`: sources: each `step.evidence` item
  ("video 14.0 s: screws out", "voice 10.2 s: '...'") plus transcript turns overlapping the step
  window (max 2, text cut to 80 chars, quoted). verified = at least one video AND one
  voice source; supported = any source; unverified = none.
- `fastener_claim(step, step_perception, refined) -> Claim | None`: only when
  `step.screws and step.screws.count > 0`. sources: "SAM: N <kind>s removed (before/after
  stills)" and "timecode re-check counted N". verified = SAM removed count == step count;
  supported = SAM found some but a different count, or refine agrees with the count;
  unverified otherwise.
- `part_claim(step, step_perception) -> Claim | None`: only when `step.target_part`. verified =
  part found with confidence >= 0.5; supported = found with lower or no confidence;
  unverified = perception ran on this step and found nothing, or did not run.
- `step_score(claims)`: mean of verified 1 / supported 0.5 / unverified 0 (0 if no claims).
- `build_proof(plan, fusion, refine, perception, transcript) -> Proof`; `Proof.score` = mean of
  step scores, rounded to 3 decimals.
- `run(job_dir, settings) -> Proof`: load, build, save, return.
- Use the step's fastener kind (`step.screws.kind`) in texts, simple plural kind + "s".

## Done when
- `tests/test_proof.py` covers each claim function: verified, supported and unverified cases;
  no fusion/refine/perception/transcript at all → every claim unverified or supported from
  step.evidence only, never a crash; `build_proof` score math; `run` writes a loadable proof.json.
- publish test: guide.proof equals the saved proof; without proof.json guide.proof is None.
- `.venv/bin/pytest -q` all pass, `ruff check .` and `ruff format --check .` clean.

## Notes
- Times in sources with one decimal and " s". Keep every function short.
