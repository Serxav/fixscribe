# Task 005: step-cuts
Branch: feat/step-cuts
Owner: Muse Code

## Goal
Turn the spoken turns in `transcript.json` into step cuts: every turn where the technician says
"step" or "paso" starts a new step. Save the result in `scenes.json`. Pure logic, no Meta calls,
no ffmpeg.

## Why this matters for judging
Use of Meta AI tooling: using the turn timestamps of Muse Voice Transcribe as a step-cut signal is
one of our "unexpected capabilities" (docs/HACKATHON_BRIEF.md). Technical depth: the cuts are
measurable against hand-written times with `eval/score.py`.

## Files to touch
- `app/pipeline/scenes.py`
- `tests/test_scenes.py` (new)

## Do not touch
- Everything else. In particular `app/pipeline/transcribe.py`, `app/pipeline/ingest.py`,
  `app/pipeline/runner.py`, `app/schemas.py`, `app/jobs.py`, `pyproject.toml`, `.env*`.
- No new dependencies.

## Input files (written by earlier stages, in `job_dir`)
- `ingest.json`: `{"duration_s": 42.0, "width": 720, "height": 1280, "has_audio": true}`
- `transcript.json`: `{"mode": "narrated", "duration_s": 42.0, "transcript": "...", "turns": [{"start_s": 1.2, "end_s": 3.4, "text": "Step one, remove the two screws"}]}`

## What to build (`app/pipeline/scenes.py`)
- `class ScenesError(Exception)`.
- `KEYWORD = re.compile(r"\b(step|paso)\b", re.IGNORECASE)` — matches "Step one", "next step",
  "siguiente paso", "PASO 3"; does **not** match "steps" or "pasó".
- `keyword_cuts(turns: list[dict], min_gap_s: float = 3.0) -> list[float]` — the `start_s` of each
  turn whose `text` matches `KEYWORD`, sorted. If two cuts are closer than `min_gap_s`, keep the first.
- `cuts_to_segments(cuts: list[float], duration_s: float, min_len_s: float = 2.0) -> list[dict]` —
  one segment per cut: `{"start_s": cut, "end_s": next_cut_or_duration_s}`, rounded to 2 decimals.
  Content before the first cut is ignored (usually an intro). A segment shorter than `min_len_s`
  is merged into the previous one (the previous one gets its `end_s`); if it is the first one, it is
  merged into the next one (the next one gets its `start_s`). Cuts at or after `duration_s` are dropped.
  No cuts → `[]`.
- `run(job_dir: Path, settings: Settings) -> dict`:
  1. Read `ingest.json` and `transcript.json`. Missing or broken file → `ScenesError` with the file name.
  2. If `transcript["mode"] == "narrated"`: `cuts = keyword_cuts(turns)`, `segments = cuts_to_segments(cuts, duration_s)`.
  3. `source` = `"voice"` if there are **at least 2 segments**, else `"none"` (then the video
     analysis will find the steps by itself, and `segments` is `[]`).
  4. Write atomically (temp file in the same folder + `os.replace`) `job_dir / "scenes.json"`:
     `{"source": "voice", "cuts": [1.2, 15.0], "segments": [{"start_s": 1.2, "end_s": 15.0}, {"start_s": 15.0, "end_s": 42.0}]}`
     and return it.

## Done when
- `.venv/bin/pytest -q` passes; `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` are clean.
- Tests:
  1. `KEYWORD` matches "Step one", "next step.", "Siguiente PASO", "paso 3"; not "steps", "pasó", "footstep".
  2. `keyword_cuts` with turns at 1.0 ("step one"), 2.0 ("step"), 10.0 ("ok"), 20.0 ("paso dos") → `[1.0, 20.0]`.
  3. `cuts_to_segments([5.0, 6.0, 20.0], 30.0)` → `[{"start_s": 5.0, "end_s": 20.0}, {"start_s": 20.0, "end_s": 30.0}]` (the 1-second segment is merged).
  4. `cuts_to_segments([], 30.0) == []`; a cut at 30.0 with `duration_s=30.0` is dropped.
  5. `run` narrated with 3 keyword turns → `source == "voice"`, 3 segments, `scenes.json` written.
  6. `run` with `mode: "silent"` → `source == "none"`, `segments == []`.
  7. `run` narrated with only 1 keyword turn → `source == "none"`.
  8. `run` without `transcript.json` → `ScenesError` mentioning `transcript.json`.
- Build `Settings(model_api_key="", data_dir=tmp_path)` in tests; write the input JSON files into `tmp_path`.
