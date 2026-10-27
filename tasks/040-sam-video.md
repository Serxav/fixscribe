# Task 040: SAM 3.1 video tracking in the Meta client
Branch: feat/sam-video
Owner: Muse Code (muse-spark-1.3, high). Web tools ON only for dev.meta.ai docs.

## Goal
`MetaClient.segment_video(video_path, concept)` sends one short clip to sam-3.1 and returns the
tracked objects per frame (box + decoded mask), with the spend counted per frame.
This is the base for the "SAM cinematic" step clips (Claude Code builds the renderer).

## HARD RULES
No deleting/moving files, no git. Never call the real API (tests mock it). Every field below is
from the docs; if the docs or `meta_sam_parser` disagree with this task, follow the docs/library
and write it under DUDAS.

## Docs (read them first)
- https://dev.meta.ai/docs/sam/segmenting — video part: `{"type": "input_video", "file_id": ...}`
  (or `video_url`); `metadata.propagation_direction` ("both" default), `metadata.mask_encoding`
  ("one_bit"), `metadata.include_confidence` ("true" string); MP4/MOV H.264; max 15,000 frames;
  max 16 objects per frame; billed per frame with a 50-frame minimum; `stream: true` recommended.
- https://dev.meta.ai/docs/sam/reading-segmentation — one line per frame `<Nf>`, stable object ids,
  frames may be skipped, frames with nothing emit no line.
- Python library already installed: `meta_sam_parser` has `video_segmentation_format`,
  `VideoSegmentationResult`, `decode_mask_to_raster`, `decode_mask_to_svg_path`. Read its source
  in `.venv/lib/python3.12/site-packages/meta_sam_parser/` to use it correctly (as
  `MetaClient.segment` does for images with `image_segmentation_format`).

## Files to touch
- `app/meta_client.py`: add `TrackedObject` and `FrameTrack` dataclasses and `segment_video`;
  keep everything else as it is.
- `tests/test_meta_client.py` (add tests) — or a new `tests/test_sam_video.py`.

## Do not touch
- every pipeline stage, routes, web, schemas, other files.

## What to build
```python
@dataclass(frozen=True)
class TrackedObject:
    object_id: int
    box: tuple[float, float, float, float]   # x1, y1, x2, y2 in source pixels
    confidence: float | None
    mask: np.ndarray | None                   # bool H x W raster in source pixels, or None
    svg_path: str | None                      # decode_mask_to_svg_path output, or None

@dataclass(frozen=True)
class FrameTrack:
    frame: int                                # the <Nf> index from the answer (not the line number)
    width: int; height: int                   # frame size from the box record (w=, h=)
    objects: list[TrackedObject]

def segment_video(self, video_path: Path, concept: str, *, max_frames: int = 600) -> list[FrameTrack]:
```
- Validate like `segment`: non-empty single noun phrase. Count frames with ffprobe
  (`nb_read_frames` via `-count_frames`, or duration × fps); if > max_frames raise ValueError
  (the caller must send short clips). Budget check BEFORE the call with
  `sam_cost(video_frames=max(50, frames))`; add the same spend after a successful answer.
- Upload the clip with the existing `upload_file`, call the Responses API with model
  `settings.sam_model`, content `[input_text concept, input_video file_id]`, metadata
  `{"mask_encoding": "one_bit", "include_confidence": "true"}` and the default propagation; always
  `delete_file` in `finally`. Use streaming only if the existing client supports it cleanly;
  otherwise a normal call and `response.output_text` (write which one under DUDAS).
- Parse with `video_segmentation_format()`; frames sorted by frame index; objects keyed by id.
- Same retry / 429 / timeout behaviour as `segment` (reuse its helpers, do not duplicate them).

## Done when
- tests with a fake OpenAI client returning a hand-written 3-frame answer (build the mask payload
  with the library's own encoder helpers if it has one, or copy the format from the docs example):
  frames parsed in order, a skipped frame is simply absent, stable ids, mask raster shape, svg path
  string, confidence parsed; budget refused before the call; file deleted on error; too many
  frames → ValueError; spend counted with the 50-frame minimum.
- `.venv/bin/pytest -q` all pass; `ruff check .` and `ruff format --check .` clean.
