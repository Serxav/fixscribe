# Task 014: sam-client (SAM 3.1 segmentation + overlay drawing)
Branch: feat/sam-client
Owner: Muse Code (muse-wonder-1.0)

## Goal
Add `MetaClient.segment(...)` for SAM 3.1 (one concept per request, parsed with `meta_sam_parser`)
and an overlay module that draws a part highlight and numbered screw markers on a keyframe.
This is the base of the screw counter and verifier (`docs/ALGORITHM.md` section 3).

## Why this matters for judging
Use of Meta AI tooling (25 %): SAM as a screw counter and verifier is our first "unexpected
capability". Demo (25 %): the numbered screw map drawn on the real photo is the image judges remember.

## Files to touch
- `app/meta_client.py` (add `segment` and a small `Detection` dataclass; change nothing else)
- `app/pipeline/overlay.py` (new)
- `tests/test_meta_client.py`, `tests/test_overlay.py` (new)

## Do not touch
Everything else. No new dependencies (`meta_sam_parser`, `cv2`, `numpy` via OpenCV, standard library).
No web tools. No real API calls.

## Facts checked by Claude Code in the docs and the installed package
- Docs: https://dev.meta.ai/docs/sam/segmenting, https://dev.meta.ai/docs/sam/reading-segmentation,
  https://dev.meta.ai/docs/sam/client-libraries.
- Request: Responses API, `model="sam-3.1"`, non-streaming works:
  ```python
  client.responses.create(
      model="sam-3.1",
      input=[
          {
              "type": "message",
              "role": "user",
              "content": [
                  {"type": "input_text", "text": concept},  # ONE short noun phrase, e.g. "screw"
                  {"type": "input_image", "image_url": data_url},  # "data:image/jpeg;base64,..."
              ],
          }
      ],
      metadata={"mask_encoding": "one_bit", "include_confidence": "true"},
  )
  ```
  One concept per request (lists like "screw, bolt" return zero matches). Zero matches = empty
  `output_text`, which is a normal result.
- Parse `response.output_text` with the installed `meta_sam_parser` 0.1.0 (verified by Claude Code):
  ```python
  from meta_sam_parser import CompletedOutcome, image_segmentation_format, decode_mask_to_raster

  parser = image_segmentation_format().create_parser()
  parser.push(text)
  result = parser.finish(CompletedOutcome()).result  # ImageSegmentationResult
  # result.records: SegmentationBoxRecord (kind="box": object_id, left, top, right, bottom,
  #   confidence) and SegmentationMaskRecord (kind="mask": object_id, mask, bounds{left,top,right,bottom});
  # result.diagnostics: problems found while parsing (log them as warnings, count only).
  # Box coordinates are half-open source-image pixels. decode_mask_to_raster(record.mask) -> bytes of
  # 0/1, row-major, mask.height x mask.width, covering `bounds` (box-local).
  ```
  Every record is **one box token followed by one mask token**; a box without a valid mask is
  dropped with a diagnostic (verified). Box `x2`/`y2` are inclusive on the wire, so the parsed
  `right`/`bottom` are `x2 + 1` / `y2 + 1`. Build valid fake answers in tests like this (verified by
  Claude Code; `_encode_raster` is a private helper of the package, use it in tests only):
  ```python
  from meta_sam_parser._mask_codec import _encode_raster


  def fake_record(obj_id, x1, y1, x2, y2, img_w, img_h):
      mw, mh = x2 - x1 + 1, y2 - y1 + 1
      payload = _encode_raster([1] * (mw * mh), mw, mh)  # already starts with "!" (one_bit)
      return (
          f"{obj_id}<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={img_w};h={img_h}|>"
          f"<|mask;x=0;y=0;data={mh},{mw},{payload}|>"
      )


  output_text = "<0f>" + ",".join(
      [fake_record(0, 10, 20, 13, 22, 100, 100), fake_record(1, 50, 50, 59, 59, 100, 100)]
  )
  ```
- Pricing: `sam_cost(images=1)` per request (already in `meta_client.py`); if
  `response.usage.images_processed` is a number, use it instead of 1.

## What to build
### `app/meta_client.py`
- `@dataclass(frozen=True) class Detection`: `object_id: str`, `box: tuple[float, float, float, float]`
  (left, top, right, bottom in pixels of the image sent), `confidence: float | None`,
  `mask: bytes | None` (0/1 raster), `mask_size: tuple[int, int] | None` (width, height),
  `mask_bounds: tuple[float, float, float, float] | None`.
- `MetaClient.segment(self, image_path: Path, concept: str, max_side: int = 1280) -> tuple[list[Detection], tuple[int, int]]`:
  1. `ValueError` if `concept` is empty or contains `,` `;` or `+`.
  2. Read the image with `cv2.imread`; `ValueError` if it cannot be read. If its longest side is above
     `max_side`, resize it (keep the aspect ratio). Encode as JPEG quality 90 and make the data URL.
  3. `self.spend.check()`, call through `_with_retries` (default retry rules), record spend under
     `settings.sam_model`.
  4. Parse as above, pair each box with the mask of the same `object_id`, return
     `(detections, (width, height))` of the image actually sent (so callers can normalize boxes).
  5. Log the number of parser diagnostics as a warning when there are any; never log the image.

### `app/pipeline/overlay.py`
- `normalize(box, size) -> tuple[float, float, float, float]` — pixels → 0..1, clamped.
- `draw_part(image, detection, size_sent)` → new image: the mask (scaled to the image) tinted with
  the signal lime `#D4FF3A` at 35 % opacity plus a 2 px lime outline (`cv2.findContours` on the mask);
  if there is no mask, a rounded lime rectangle from the box.
- `draw_screws(image, boxes, numbers)` → new image: for each screw a filled graphite circle
  (`#0E0F11`, 85 % opacity) with a 2 px lime ring at the box center, radius ~ max(14 px, box size),
  and its number in white, centered (`cv2.putText`, `FONT_HERSHEY_SIMPLEX`, bold enough to read on a phone).
- `save_jpeg(image, path, quality=88)` — atomic (temp file + `os.replace`).
Keep these functions pure (no file reads inside except `save_jpeg`).

## Done when
- `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .` pass.
- Tests (fakes only):
  1. `segment` sends model `sam-3.1`, the concept, a `data:image/jpeg;base64,` URL, and the metadata above.
  2. A fake answer with the two records of `fake_record` above → 2 detections with boxes
     `(10, 20, 14, 23)` and `(50, 50, 60, 60)` and a mask each; empty
     `output_text` → `[]`; spend recorded once at `sam_cost(images=1)`.
  3. A 4000×3000 test image is resized so the longest side is 1280 and the returned size says so.
  4. `"screw, bolt"` → `ValueError`, no call. Budget reached → `BudgetExceeded`, no call.
  5. Overlay: `draw_screws` on a gray image changes pixels at each box center and leaves a far corner
     unchanged; `draw_part` without a mask draws the outline; `save_jpeg` leaves no temp file.
