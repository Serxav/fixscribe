# Task 022: refine (Spark pass 2 on short timecoded clips of uncertain steps)
Branch: feat/refine
Owner: Muse Code (muse-wonder-1.0)

## Goal
New optional stage `app/pipeline/refine.py` between `fusion` and `plan`: for the few steps that are
uncertain or have screws, cut a short clip of that step from the proxy **with the absolute video
time burned into every frame**, send it to Muse Spark with the strict per-step schema, and save the
answers in `refine.json`. Spark sees a short clip (more frames per second of action) and reads exact
times from the image instead of guessing them. Spec: `docs/ALGORITHM.md` sections 1–2; audit F11.

## Why this matters for judging
Technical depth + Use of Meta AI: a second, focused Spark pass with temporal grounding is how a
senior team turns a fragile LLM timestamp into a measured one. `eval/run_eval.py` will compare v2
with and without this stage.

## Files to touch
- `app/pipeline/refine.py` (new), `tests/test_refine.py` (new)

## Do not touch
`app/schemas.py` (use `Refine`, `RefinedStep`, `REFINE_JSON_SCHEMA`, `Analysis`, `Fusion`,
`Transcript`, `IngestInfo`), `prompts/refine_v1.md` (Claude Code wrote it: fill its placeholders
`<<TITLE>> <<INSTRUCTION>> <<START_S>> <<END_S>> <<SCREWS>> <<TURNS>>` with `str.replace`),
`app/meta_client.py`, `app/pipeline/plan.py` (Claude Code applies `refine.json` there), `runner.py`,
`pyproject.toml`, `.env*`. No new dependencies. No web tools. Never call the real API in tests.

## Facts
- Our ffmpeg has **no `drawtext`**: burn the timecode with OpenCV (`cv2.putText` on a dark rounded
  box, white text `t=12.4 s`, top-left, readable at 480 p) and encode the frames with ffmpeg through a
  pipe (`-f rawvideo -pix_fmt bgr24 -s WxH -r FPS -i - -c:v libx264 -crf 26 -pix_fmt yuv420p`).
- Read the proxy with OpenCV; the proxy is constant frame rate (task 018), so the time of each frame
  is `CAP_PROP_POS_MSEC`.
- Spark calls go through `MetaClient.upload_file`, `respond(..., text={"format": {"type":
  "json_schema", "name": "refined_step", "schema": REFINE_JSON_SCHEMA, "strict": True}},
  max_output_tokens=8000, timeout_s=300, retry_timeouts=False)` and `delete_file` in `finally`
  (same pattern as `app/pipeline/analyze.py`). Build the client with `MetaClient(settings, job_dir=job_dir)`.

## What to build
- `select_steps(analysis, fusion) -> list[int]` — step indexes (1-based, in Spark's time order, like
  fusion) with fused confidence < `0.6` **or** `screw_count > 0`, lowest confidence first, at most
  `MAX_STEPS = 4`.
- `clip_window(start, end, duration) -> (a, b)` — `[start − 2, end + 2]` clamped to the video,
  at most `MAX_CLIP_S = 30` (centred on the step if longer).
- `make_timecoded_clip(proxy: Path, a: float, b: float, dst: Path, short_side: int = 480) -> Path`.
- `refine_step(...) -> RefinedStep` — upload, ask, parse (strict JSON → `RefinedStep` with `index`),
  then **sanity checks**: times must lie inside the clip window (else keep the fused times and set
  confidence to `min(confidence, 0.4)`), `end_s > start_s`.
- `run(job_dir, settings, client=None) -> Refine`: inputs `Analysis` (required), `Fusion`,
  `Transcript`, `IngestInfo` (optional except ingest). A failing step (MetaError, bad JSON) goes to
  `skipped` with a short reason and the stage continues; `BudgetExceeded` stops cleanly. Save with
  `artifacts.save`. Temporary clips live in `job_dir / "refine"` and are deleted at the end.

## Done when
- `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .` pass.
- Tests (fake client; synthetic proxy made with ffmpeg in `tmp_path`):
  1. `select_steps`: low-confidence and screw steps chosen, order, `MAX_STEPS`.
  2. `clip_window` clamps and centres.
  3. The timecoded clip has the expected duration (±0.1 s), 480 px short side, and the top-left box
     is brighter text on a dark box (check pixel statistics in that region vs the rest).
  4. A fake Spark answer inside the window → a `RefinedStep` with those times; an answer outside the
     window → fused times kept and confidence ≤ 0.4.
  5. The prompt sent contains the title, the draft times and the turns inside the window only.
  6. `files.delete` called even when `respond` fails; failures go to `skipped`.
- Report: clip size in KB for a 10 s step and the time to build it.
