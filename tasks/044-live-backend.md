# Task 044: live mode backend — "where am I and what do I do now?" from one camera frame
Branch: feat/live
Owner: Muse Code (muse-spark-1.3, high)

## Goal
While the user repairs or builds, the phone sends one camera frame every ~2 s. The server asks
Spark (image + the guide) which step the user is on, whether it looks right, and what to do next,
and returns a short answer the page can show and speak. Backend + JSON route only (Claude Code
builds the camera page).

## HARD RULES
No deleting/moving files, no git. Tests never call the real API.

## Files to touch
- `app/pipeline/live.py` (new), `prompts/live_v1.md` (new)
- `app/routes/ask.py` (empty today: put the live route here), `app/main.py` (include_router line)
- `tests/test_live.py` (new)

## Do not touch
- `app/schemas.py`, `analyze.py`, `motion.py`, `publish.py`, `runner.py`, web files (Claude Code
  edits them now). Define the answer model locally in `live.py` (Claude Code moves it later).

## What to build
`app/pipeline/live.py`:
```python
class LiveAnswer(Strict-like pydantic, extra="forbid"):
    step: int            # 1..N, the guide step the user is on (0 = not started / not visible)
    status: Literal["on_track", "wrong", "done_step", "unclear"]
    say: str             # one short sentence for the voice, in the guide language (<= 20 words)
    next: str            # the next action, imperative, <= 15 words
    look_for: str        # 1-3 common English words SAM can find on the frame ("metal bolt"), or ""
    confidence: float    # 0..1
LIVE_JSON_SCHEMA = strict JSON schema of the same fields (use app.schemas._object style: write a
local _object helper or import `_object` from app.schemas — importing is fine).
MAX_FRAME_BYTES = 4 * 1024**2
MAX_LIVE_CALLS_PER_JOB = 300   # protects the budget (~0.003 $ each)
def live_turn(job_dir, settings, frame: bytes, last_step: int = 0, client=None) -> LiveAnswer
```
- Load the guide (`artifacts.load(job_dir, Guide)`); professional_only guide → return
  `LiveAnswer(step=0, status="unclear", say=<first safety reason>, next="", look_for="",
  confidence=1)` without calling Spark.
- Frame: Pillow open + `ImageOps.exif_transpose`, downscale to max side 768, JPEG quality 80,
  write to `job_dir / "live" / "frame.jpg"` (overwrite atomically with `artifacts.atomic_path`).
- Prompt `prompts/live_v1.md` with `<<LANGUAGE>>` (guide.language), `<<STEPS>>` (one line per step:
  "N. title — instruction — fasteners"), `<<LAST_STEP>>`. Rules in the prompt: judge ONLY what is
  visible; never invent; if hands/object not visible → "unclear"; prefer the step after
  `last_step` when ambiguous; `say` speaks to the user ("Good, now…"); `look_for` names the part or
  fastener to point at.
- `ask_json(client, settings, name="live_turn", schema=LIVE_JSON_SCHEMA, prompt=...,
  images=[frame_path], max_output_tokens=4000, timeout_s=30)`; clamp `step` into 0..N; count calls
  in `live/calls.txt` (int, atomic write) and refuse with `LiveError("live limit")` over the max.
- `class LiveError(Exception)`; bad image / too big → LiveError with a clear message.

Route in `app/routes/ask.py`: `POST /api/live/{job_id}` multipart field `frame` (+ optional form
field `last_step` int). Use `app.routes.common.load_guide` for 404s; run `live_turn` in a
threadpool; LiveError → 400 JSON `{"error": ...}` ("live limit" → 429); return the LiveAnswer JSON.

## Done when
- tests (fake client, TestClient): normal answer, step clamped, professional_only answers without
  calling Spark, too-big frame 400, limit 429, bad id 404, EXIF-rotated JPEG accepted.
- `.venv/bin/pytest -q` all pass; `ruff check .` and `ruff format --check .` clean.
