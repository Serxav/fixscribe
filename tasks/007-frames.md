# Task 007: frames
Branch: feat/frames
Owner: Muse Code

## Goal
For every step in `guide.json`: pick the sharpest frame near the key moment (±1 s), save it as a
JPEG, cut a 6-second silent loop clip, and write their paths and `keyframe_s` back into `guide.json`.
No Meta calls.

## Why this matters for judging
Demo + Impact: a clear photo and a short looping clip per step are what a technician (and a judge
watching the 3-minute video) actually looks at. A blurry keyframe makes the whole guide look bad,
and the SAM highlight and screw map are drawn on this frame later.

## Files to touch
- `app/pipeline/frames.py`
- `tests/test_frames.py` (new)

## Do not touch
- Everything else. In particular `app/schemas.py`, `app/pipeline/guide.py`, `app/pipeline/runner.py`,
  `app/pipeline/ingest.py`, `pyproject.toml`, `.env*`.
- No new dependencies: `opencv-python-headless` (import `cv2`) and `ffmpeg` via `subprocess.run`
  (list of args, never `shell=True`) are allowed.

## Input (in `job_dir`)
- `video.mp4` (from ingest) and `guide.json` (a `Guide` from `app/schemas.py`; read it with
  `Guide.model_validate_json`).

## What to build (`app/pipeline/frames.py`)
- `class FramesError(Exception)`.
- `CLIP_SECONDS = 6.0`, `WINDOW_S = 1.0`, `SAMPLE_FPS = 5`.
- `sharpness(image) -> float` — variance of the Laplacian of the grayscale image:
  `cv2.Laplacian(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()`.
- `key_moment(step: Step) -> float` — the first `evidence` item with `source == "video"` whose `t_s`
  is inside the step; otherwise the middle of the step.
- `best_frame(capture, start_s: float, end_s: float) -> tuple[float, Any] | None` — read frames every
  `1 / SAMPLE_FPS` seconds from `start_s` to `end_s` (`capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000)`
  then `capture.read()`), return `(t, frame)` with the highest `sharpness`, or `None` if no frame reads.
  The window is `[key - WINDOW_S, key + WINDOW_S]` clipped to `[step.start_s, step.end_s]`.
- `clip_range(step: Step, keyframe_s: float, duration_s: float) -> tuple[float, float]` — `(start, length)`:
  `length = min(CLIP_SECONDS, step.end_s - step.start_s)`; `start = keyframe_s - length / 2`,
  then moved so the clip stays inside the step and inside `[0, duration_s]`.
- `cut_clip(video: Path, start: float, length: float, dst: Path) -> None` —
  `ffmpeg -y -v error -ss START -i VIDEO -t LENGTH -an -c:v libx264 -preset veryfast -crf 28 -pix_fmt yuv420p -movflags +faststart DST`
  (timeout 120 s; non-zero exit → `FramesError` with the last 3 lines of stderr).
- `run(job_dir: Path, settings: Settings) -> Guide`:
  1. Missing `video.mp4` or `guide.json` → `FramesError` naming the file. `cv2.VideoCapture` that
     does not open → `FramesError("cannot open video.mp4")`.
  2. For each step: best frame → `steps/NN.jpg` (`NN` = step index with 2 digits, JPEG quality 85,
     `cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])`), then clip → `steps/NN.mp4`.
     Update the step with `keyframe_s` (rounded to 2 decimals), `image="steps/NN.jpg"`,
     `clip="steps/NN.mp4"` (paths relative to `job_dir`), using `step.model_copy(update=...)`.
  3. If one step fails (no frame, ffmpeg error), log a warning, leave that step unchanged and
     continue: one bad step must not fail the job.
  4. Write the updated guide back to `guide.json` atomically (temp file + `os.replace`) with
     `guide.model_dump(mode="json")`, and return it. Always `capture.release()` (use `try/finally`).

## Done when
- `.venv/bin/pytest -q` passes; `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` are clean.
- Tests (skip if `shutil.which("ffmpeg") is None`), with a 6-second `testsrc` video at 720x1280
  made in `tmp_path` (`ffmpeg -y -v error -f lavfi -i testsrc=size=720x1280:rate=30 -t 6 -c:v libx264 -pix_fmt yuv420p video.mp4`)
  and a `guide.json` with 2 steps (0–3 s and 3–6 s) built with the `Guide` / `Step` models:
  1. `run` → `steps/01.jpg`, `steps/02.jpg`, `steps/01.mp4`, `steps/02.mp4` exist; each `keyframe_s`
     is inside its step and within ±1 s of the middle; the saved `guide.json` validates.
  2. Clip length: probe `steps/01.mp4` with ffprobe → about 3 s (step shorter than 6 s), no audio stream.
  3. `sharpness`: an image and its `cv2.GaussianBlur(img, (21, 21), 0)` → the original is sharper.
  4. `key_moment` uses a video evidence `t_s` inside the step, and ignores audio evidence and
     evidence outside the step.
  5. `clip_range` for a 20 s step with keyframe at its start → the clip starts at the step start and lasts 6 s.
  6. A step whose time range is past the end of the video → that step keeps `image is None`, the other step is done.
  7. Missing `guide.json` → `FramesError` mentioning `guide.json`.
