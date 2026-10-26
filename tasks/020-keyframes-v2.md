# Task 020: keyframes-v2 (pick the frame where the part is sharp, steady and not covered)
Branch: feat/keyframes-v2
Owner: Muse Code (muse-wonder-1.0)

## Goal
Rewrite keyframe selection in `app/pipeline/frames.py` so the chosen frame shows the **part**
sharply, with a steady camera and as little hand as possible — measured, not assumed — and save it
as a native-resolution still from the original (for SAM) plus a display JPEG.
Audit findings F4, F16 (`tasks/AUDIT_FOUNDATIONS.md`); read it and `docs/ENGINEERING_STANDARD.md`.

## Why this matters for judging
Demo + Technical depth: the keyframe is the photo of every step, and the image SAM looks at. Today
a whole-frame Laplacian prefers a blurred part on a busy mat (69,704 vs 197, measured).

## Files to touch
- `app/pipeline/frames.py`, `tests/test_frames.py`

## Do not touch
Everything else. Use, do not change: `app/schemas.py` (`Plan`, `Frames`, `StepMedia` with the new
`still` field, `Signals`, `IngestInfo`), `app/artifacts.py`, `app/pipeline/media.py`
(`extract_still(original, source, t, dst, max_side=None)`), `app/pipeline/ingest.py`
(`find_original`). No new dependencies, no web tools, no Meta calls.

## What to build
1. **Candidates** for a step: sample the **proxy** `video.mp4` every 0.25 s over the whole step
   (not only ±1 s), read with OpenCV, timestamps from `CAP_PROP_POS_MSEC`.
2. **Score** each candidate (all terms normalized within the step, so they are comparable):
   - `roi_sharpness`: variance of the Laplacian on the central ROI (middle 60 % of width and height)
     of the gray frame — the part is almost always near the centre; never on the whole frame.
   - `steadiness`: from `signals.json` (optional): `1 − motion_energy` at the nearest sample time,
     normalized; if there are no signals, compute the frame difference with the previous candidate.
   - `hand_fraction`: share of ROI pixels inside a skin range in YCrCb (Cr 133–173, Cb 77–127),
     a cheap proxy for "a hand covers the part".
   - `score = z(roi_sharpness) + 0.5·z(steadiness) − 1.0·hand_fraction·3` (write the formula in a
     docstring; tune the weights only with a test that justifies them).
   Keep the best candidate; ties → closer to the step's video evidence time, then to the middle.
3. **Outputs per step** (all atomic: temp file + `os.replace`):
   - `stills/NN.png` — native still from the **original** at the chosen time via
     `media.extract_still(...)` (no `max_side`), written to `StepMedia.still`;
   - `steps/NN.jpg` — display JPEG from that still, long side ≤ 1600 px, quality 88;
   - `steps/NN.mp4` — the loop clip as today but encoded at CRF 20 (not 28).
   If the original cannot give a still (missing, decode error), fall back to the proxy frame for
   `steps/NN.jpg` and leave `still=None`; log it, never fail the stage for one step.
4. Write `frames.json` with `artifacts.save` as today.

## Done when
- `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .` pass.
- Tests (ffmpeg/OpenCV fixtures in `tmp_path`; you may build frame sequences with OpenCV and encode
  them with ffmpeg through a pipe or image sequence):
  1. **Busy background trap**: a step whose frames alternate between (A) a sharp dark "part" in the
     centre on a plain background and (B) the same part motion-blurred with a high-texture border.
     The chosen keyframe is an A frame (whole-frame Laplacian would choose B — assert that too).
  2. **Steadiness**: half the step shaky (random translation), half steady, same content → the
     keyframe is in the steady half.
  3. **Hand**: same sharp frame, one version with a skin-coloured blob covering 40 % of the ROI →
     the uncovered frame wins.
  4. `stills/NN.png` exists at the original's native size (e.g. 1080×1920 for a 1080×1920 portrait
     original while the proxy is 720×1280); `steps/NN.jpg` long side ≤ 1600.
  5. Original missing → `steps/NN.jpg` still produced from the proxy, `still is None`.
  6. Existing frames tests still pass (adapt where the behaviour intentionally changed).
- Report: the scores of the trap test (A vs B with your metric and with whole-frame Laplacian) and
  the time per step on a 10 s step.
