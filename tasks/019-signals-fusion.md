# Task 019: signals-v2 + voice cut intervals + fusion
Branch: feat/signals-fusion
Owner: Muse Code (muse-wonder-1.0)

## Goal
Make the two independent step signals trustworthy and fuse them with Spark's steps:
1. `signals.py` v2 — true timestamps, pauses on the smoothed curve with an absolute floor, and
   **camera-shake compensation** so a shaky hand-held phone does not look like hand activity.
2. `scenes.py` — voice cuts become intervals (the whole spoken turn), one keyword is enough.
3. `fusion.py` (new) — snap Spark's step boundaries to voice/visual candidates and compute an
   agreement-based confidence, written to its own artifact `fusion.json`.
Audit findings F1 (signals part), F9, F10, F11 in `tasks/AUDIT_FOUNDATIONS.md`; spec in
`docs/ALGORITHM.md` section 2. Read both and `docs/ENGINEERING_STANDARD.md` first.

## Why this matters for judging
Technical depth (20 %): this is the difference between "one LLM call" and an algorithm whose
every boundary says where its evidence came from. Use of Meta AI (25 %): Muse Voice and Muse Spark
are fused, not just called.

## Files to touch
- `app/pipeline/signals.py`, `app/pipeline/scenes.py`, `app/pipeline/fusion.py` (new)
- `tests/test_signals.py`, `tests/test_scenes.py`, `tests/test_fusion.py` (new)

## Do not touch
`app/schemas.py` (the models `Signals`, `Candidate`, `Scenes`, `Segment`, `Fusion`, `FusionStep`,
`Analysis` are ready — use them), `app/artifacts.py`, `app/pipeline/ingest.py`, `runner.py`,
`analyze.py`, `pyproject.toml`, `.env*`. No new dependencies. No web tools. No Meta calls.

## Rules for all three
Read and write only through `app.artifacts` (`load`, `load_optional`, `save`) with the models
above; delete the old private `_read_json` / `_write_json_atomic` helpers in these files.

## 1. `signals.py` v2
- Timestamps: every sample's `t` = `capture.get(cv2.CAP_PROP_POS_MSEC) / 1000` right after
  `retrieve()` (never `frame_index / fps`). `duration_s` = last timestamp + one sample interval.
- Camera-shake compensation: before the frame difference, estimate the global shift between the
  previous and current gray proxy with `cv2.phaseCorrelate` (float32 inputs) and shift the previous
  frame by it (`cv2.warpAffine`); motion energy = mean abs difference of the aligned frames, ignoring
  a border of `ceil(max(|dx|,|dy|))` pixels. Keep the raw energy too only if useful for tests.
- Pauses on the **smoothed** curve: below `max(0.004, 35th percentile)` **and** below `0.5 × median`,
  lasting ≥ `MIN_PAUSE_S`.
- Output: `Signals` model saved with `artifacts.save`.

## 2. `scenes.py`
- For each turn whose text matches `KEYWORD`: cut at the turn start, and an interval
  `Segment(start_s=turn.start_s, end_s=turn.end_s)` in `cut_intervals`.
- `source = "voice"` when there is **at least 1** cut (today it needs 2). Segments: one per cut (as
  today) plus, when the first cut is at least 3 s after 0, a first segment `[0, first_cut]`.
- Read `Transcript` with `load_optional` (missing = silent) and `IngestInfo` with `load`.

## 3. `fusion.py` (new stage, owns `fusion.json` only — never rewrite `analysis.json`)
- Inputs: `Analysis` (required), `Scenes` and `Signals` (optional).
- Candidates: voice cuts (weight 1.0; a voice cut may be snapped to anywhere inside its interval:
  use the point of the interval closest to Spark's time), pauses (0.6 × score), scenes (0.4 × score).
- For each step (sorted by Spark start): snap `start_s`, then `end_s`, to the best unused candidate
  within `SNAP_WINDOW_S = 1.5`, maximizing `weight − 0.2 × |Δt|`; else keep Spark's time (source "spark").
  The end of step i and the start of step i+1 may share one candidate when they were < 0.5 s apart.
  Refuse a snap that would make `end ≤ start` or overlap the previous step.
- `agreement`: voice 1.0, pause/scene 0.8, spark 0.6; if the job has **no candidates at all**, 1.0.
  `confidence = round(min(1, spark_confidence × agreement), 3)`.
- Save `Fusion(candidates=n, steps=[FusionStep(...)])`. Missing/broken `analysis.json` → `FusionError`
  with the artifact message. `run(job_dir, settings) -> Fusion`.

## Done when
- `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .` pass.
- Signals tests (ffmpeg fixtures in `tmp_path`, 320×568):
  1. VFR clip (60 fps for 2 s then 30 fps; recipe: `-vf "setpts='if(lt(N,120),N/(60*TB),(120+(N-120)*2)/(60*TB))'" -fps_mode vfr`)
     → every sample `t` is within 0.05 s of its true time (compare with `ffprobe` frame `pts_time`).
  2. **Shake only**: a still picture moved by a small random translation every frame (e.g. `crop`
     with an `x`/`y` expression from a slightly larger still) → mean compensated energy < 30 % of the
     raw (uncompensated) mean; report both numbers.
  3. Pause clip (move, still, move) → one pause candidate in the still part, as today.
  4. Constant accelerating motion → no pause candidate (Wonder's audit found a false one at 3.4 s).
- Scenes tests: interval stored; one keyword → `source == "voice"`; intro segment rule.
- Fusion tests: the 6 cases of `.muse-runs`-style spec below, plus "voice interval snap":
  1. start 10.4, voice cut 10.0, pause 10.3 → 10.0, "voice". 2. only a pause 2 s away → stays, "spark", 0.6.
  3. steps 0–10 and 10–20, pause at 10.5 → both boundaries 10.5. 4. a snap that inverts a step is refused.
  5. no candidates → unchanged times and confidence. 6. `run` writes `fusion.json` and does not touch `analysis.json`.
  7. voice interval [9.0, 12.0] and Spark start 11.2 → snapped to 11.2 inside the interval, source "voice".
- Report: the shake numbers, and anything in the spec you disagree with (with a reason).
