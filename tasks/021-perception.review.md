# Review 021: perception — one foundation fix

Very good work: crop mapping, NMS, reading order, budget handling and the overlay rings are right.
One real-video problem remains, and it is the core of the screw ledger:

1. `app/pipeline/perception.py` `_process_step` (the "removed" loop): the before and after stills are
   taken ~1 s apart from a **hand-held phone**. The camera moves, so a screw that stays in place can
   move more than `SAME_SCREW × diagonal` in the image and be counted as removed (and the ROI crop
   is no longer on the same area). Fix:
   - Add `align_after_to_before(before_img, after_img) -> np.ndarray | None`: ORB features
     (`cv2.ORB_create(2000)`) on the gray stills (downscaled to ≤ 1280 px for speed), match with
     `BFMatcher(NORM_HAMMING, crossCheck=True)`, estimate a **similarity** transform with
     `cv2.estimateAffinePartial2D(..., method=cv2.RANSAC)`; return the 2×3 matrix scaled back to full
     size, or `None` when there are fewer than 15 inliers.
   - Crop the "after" ROI from the after still **warped into the before still's frame**
     (`cv2.warpAffine`), so both crops show the same area; compare in before-still coordinates.
   - When alignment fails, still compare but add the note "Camera moved too much to verify the
     screws." and mark those records' confidence ≤ 0.5.
   Tests: (a) after still = before still shifted by 60 px right and 25 px down and rotated 3°, with
   one screw removed → exactly 1 removed (without alignment it would be several — assert the
   unaligned comparison gives more, to prove the test catches the problem); (b) a featureless after
   still → alignment `None`, the note, confidence ≤ 0.5.

Then run `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .` and
report again (with the inlier count and alignment error in pixels of test (a)).
