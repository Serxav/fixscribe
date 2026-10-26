# Task 012: visual-signals (motion and scene-change signals from the video)
Branch: feat/visual-signals
Owner: Muse Code (muse-wonder-1.0)

## Goal
New pipeline stage `signals`: read `video.mp4` with OpenCV and compute two local signals —
**motion energy** (hands stop between actions) and **scene change** — and turn them into ranked
**candidate step boundaries** saved in `signals.json`. No Meta calls: this signal is free.

## Why this matters for judging
Technical depth (20 %) + Impact (30 %): today silent videos depend only on one Spark call. These
candidates are the second independent signal of the algorithm v2 (`docs/ALGORITHM.md`, section 1),
fused later with voice cuts and Spark's steps, and measured in `eval/`. Read `docs/ALGORITHM.md` first.

## Files to touch
- `app/pipeline/signals.py` (new)
- `tests/test_signals.py` (new)

## Do not touch
Everything else (in particular `app/pipeline/runner.py`: Claude Code wires the stage). No new
dependencies (`opencv-python-headless` as `cv2`, the standard library, and `ffmpeg` in tests only).
No web tools. Do not call the Meta API.

## What to build (`app/pipeline/signals.py`)
- `class SignalsError(Exception)`.
- Constants: `SAMPLE_FPS = 4`, `PROXY_WIDTH = 160`, `MIN_PAUSE_S = 0.75`, `MIN_GAP_S = 2.0`, `EDGE_S = 1.0`.
- `sample_frames(video: Path) -> Iterator[tuple[float, ndarray]]` — open with `cv2.VideoCapture`,
  read sequentially (use `grab()` for skipped frames and `retrieve()` only for the sampled ones,
  every `round(src_fps / SAMPLE_FPS)` frames; if fps is 0 or unknown assume 30), resize to
  `PROXY_WIDTH` wide keeping the aspect ratio, yield `(t_seconds, frame_bgr)`. Always release.
- `compute_signals(video: Path) -> dict` — one pass:
  - motion energy = mean absolute difference of consecutive **gray** proxies / 255 (first sample = 0.0);
  - scene score = `cv2.compareHist(h_prev, h, cv2.HISTCMP_BHATTACHARYYA)` on HSV histograms
    (H 32 bins, S 32 bins, normalized) of consecutive samples (first = 0.0).
  Returns `{"fps": 4, "duration_s": float, "motion": [[t, e], ...], "scene": [[t, s], ...]}` with values rounded to 4 decimals.
- `smooth(values: list[float], window: int = 3) -> list[float]` — centered moving average (same length).
- `find_pauses(motion: list[list[float]], min_len_s: float = MIN_PAUSE_S) -> list[dict]` — adaptive
  threshold = 35th percentile of the smoothed energy (but at least 0.002); a pause is a run of samples
  below it lasting ≥ `min_len_s`; candidate `{"t": center, "kind": "pause", "score": s}` with
  `s = clamp(1 - mean_in_run / threshold, 0, 1)`, rounded to 3 decimals.
- `find_scene_changes(scene: list[list[float]]) -> list[dict]` — samples whose score is above
  `max(0.3, mean + 3 × std)` and higher than both neighbours → `{"t", "kind": "scene", "score": min(1, score)}`.
- `rank_candidates(candidates: list[dict], duration_s: float) -> list[dict]` — drop candidates within
  `EDGE_S` of the start or the end; when two are closer than `MIN_GAP_S`, keep the one with the higher
  score; return sorted by `t`.
- `run(job_dir: Path, settings: Settings) -> dict` — missing `video.mp4` → `SignalsError("missing video.mp4")`;
  a video that does not open or gives no frames → `SignalsError("cannot read video.mp4")`. Writes
  `signals.json` atomically (temp file + `os.replace`) = `compute_signals(...)` plus `"candidates": rank_candidates(...)`,
  and returns it.

## Done when
- `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .` pass.
- Tests build tiny synthetic videos with ffmpeg in `tmp_path` (skip if no ffmpeg), 320x568, 30 fps:
  1. **Pause**: 3 s of moving `testsrc2` + 2 s of a still frame + 3 s of moving `testsrc2`
     (e.g. `-f lavfi -i testsrc2=...:duration=3`, a still from `color=gray:...:duration=2`
     — or `tpad`/`loop` of one frame — joined with the `concat` filter). Expect one `pause`
     candidate with `3.0 <= t <= 5.0`.
  2. **Scene change**: 2 s `color=red` + 2 s `color=blue` → one `scene` candidate with `1.5 <= t <= 2.5`.
  3. Pure tests for `smooth`, `find_pauses` (a hand-made curve), `find_scene_changes`, and
     `rank_candidates` (edge drop, min-gap keeps the higher score, sorted).
  4. `run` writes a `signals.json` whose keys are `fps, duration_s, motion, scene, candidates`;
     missing video → `SignalsError`.
  5. Speed: a 60 s `testsrc2` video (320x568, 30 fps) is processed by `compute_signals` in under 5 s
     (assert it with `time.perf_counter()`; no custom pytest markers).
