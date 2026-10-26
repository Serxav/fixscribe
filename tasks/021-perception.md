# Task 021: perception (SAM part highlight + before/after screw ledger + overlay)
Branch: feat/perception
Owner: Muse Code (muse-wonder-1.0)

## Goal
New stage `app/pipeline/perception.py`: for each step, ask SAM 3.1 for the **part** on the keyframe
still and for **screws** on stills taken just **before** and just **after** the step, on
native-resolution **crops** around the part. A screw present before and missing after was removed
in that step → it becomes a numbered entry of the **screw ledger**. Draw an overlay that highlights
the part and rings each removed screw without hiding it. Save everything in `perception.json`.
Spec: `docs/ALGORITHM.md` section 3; audit F3, F5, F13, F14 in `tasks/AUDIT_FOUNDATIONS.md`.

## Why this matters for judging
Use of Meta AI tooling (25 %): "SAM as a screw counter and verifier" is our first unexpected
capability; today it does not exist. Impact: a technician sees which screws come out and that the
same screws go back.

## Files to touch
- `app/pipeline/perception.py` (new), `app/pipeline/overlay.py` (fix the markers)
- `tests/test_perception.py` (new), `tests/test_overlay.py`

## Do not touch
`app/schemas.py` (use `Perception`, `StepPerception`, `PartHighlight`, `ScrewRecord`, `NormBox`,
`Plan`, `Frames`, `IngestInfo`), `app/meta_client.py` (use `MetaClient.segment(image_path, concept,
max_side)` → `(detections, (w, h))`, `Detection(object_id, box, confidence, mask, mask_size,
mask_bounds)`), `app/pipeline/media.py` (`extract_still`), `app/pipeline/ingest.py` (`find_original`),
`app/artifacts.py`, `runner.py`, `publish.py`. No new dependencies. No web tools. **Never call the
real API in tests**: inject a fake client (`run(job_dir, settings, client=None)`).

## What to build (`perception.py`)
- Constants: `MAX_STEPS = 12` (SAM budget per job), `BEFORE_S = 0.5`, `AFTER_S = 0.5`,
  `ROI_GROW = 1.6`, `MIN_CROP_SIDE = 900` (upscale smaller crops to at least this with INTER_CUBIC),
  `MIN_CONFIDENCE = 0.3`, `NMS_IOU = 0.5`, `SAME_SCREW = 0.04` (fraction of the still diagonal).
- `part_concept(target_part: str | None, removes: list[str]) -> str | None` — one short noun phrase
  for SAM (one concept per call; no commas): lower case, drop articles, keep the last 1–2 words
  ("the battery connector bracket" → "connector bracket"); `None` if nothing usable.
- Per step (only steps with `screws.count > 0` or a part concept; at most `MAX_STEPS`, longest-screw
  steps first):
  1. Keyframe still: `frames.json` `still` if present, else extract one at the step middle from
     the original (`extract_still` into `stills/NN.png`).
  2. Part: `segment(keyframe_still, concept, max_side=1600)` → best detection by confidence ≥
     `MIN_CONFIDENCE` → `PartHighlight` with a `NormBox` (normalize by the size SAM returned).
  3. Screws (only if the plan step has screws): stills at `start_s − BEFORE_S` and `end_s + AFTER_S`
     (clamped to the video) into `stills/NN_before.png` / `NN_after.png`. ROI = the part box grown by
     `ROI_GROW` (whole frame if no part). Crop the same ROI on both stills, upscale to
     `MIN_CROP_SIDE`, `segment(crop, "screw")`, map boxes back to the full still (undo upscale and
     crop offset), filter by confidence, remove duplicates by IoU > `NMS_IOU`.
  4. Removed = before-boxes with **no** after-box whose centre is within `SAME_SCREW × diagonal`.
     Number them in reading order (top-to-bottom rows, then left-to-right) → `ScrewRecord`s with ids
     `S1, S2, …` continuing across steps. Boxes are normalized to the keyframe still (the stills
     share the same size; if not, scale).
  5. Notes: e.g. "SAM found 3 screws removed, the analysis counted 4." when they differ; "No part
     found for 'connector bracket'." Keep them short and factual.
  6. Overlay `steps/NN_overlay.jpg` (long side ≤ 1600, atomic) from the keyframe still: part highlight
     + numbered screw markers.
- One step failing (decode error, `MetaError`) → a note on that step, continue. `BudgetExceeded` →
  stop asking SAM, keep what was found, note it. Count every SAM call in `sam_calls`.
- `run(job_dir, settings, client=None) -> Perception` → `artifacts.save`.

## Overlay fix (`overlay.py`)
Today a marker is a filled disc of at least 28 px that hides a ~6 px screw. Draw instead a **ring**
(no fill) of radius `max(6 px, 0.6 × box diagonal)` around the screw, and the number in a small
graphite label with a lime ring placed **outside** the screw (offset up-right, kept inside the image)
with a thin leader line. Give `draw_screws` the same coordinate contract as `draw_part` (it takes
normalized boxes and the target image size).

## Done when
- `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .` pass.
- Tests with a fake client whose `segment` returns prepared `Detection`s depending on the concept
  and the image it receives (read the image size from the file), and synthetic stills (gray image,
  a dark rectangle as the part, small light circles as screws):
  1. Before has 4 screws, after has 1 at the same place as one of them → 3 removed, numbered in
     reading order, ids S1–S3; a second step continues with S4.
  2. Crop mapping: a screw at a known pixel position in the full still ends up at the right
     normalized box after crop + 2× upscale (tolerance 1 px).
  3. NMS: two overlapping duplicate detections → one screw.
  4. Analysis says 4, SAM finds 3 → the note says so.
  5. No part detection → ROI = whole frame, note "No part found …".
  6. `MAX_STEPS` respected; `BudgetExceeded` mid-way keeps earlier results; `sam_calls` correct.
  7. Overlay: the pixel at each screw centre is **unchanged** (not covered); pixels on the ring and
     the label change; label stays inside the image near an edge.
  8. `part_concept` cases ("the battery connector bracket", "", None, "Back cover").
- Report: how many SAM calls a 5-step guide with 3 screw steps makes, and the cost at
  `sam_cost(images=1)` per call.
