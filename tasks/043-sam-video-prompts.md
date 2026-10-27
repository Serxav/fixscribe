# Task 043: SAM 3.1 video tracking seeded with box prompts
Branch: feat/sam-video-prompts
Owner: Muse Code (muse-spark-1.3, high). Web tools ON only for dev.meta.ai docs.

## Goal
Track EXACTLY the objects we point at, not every object matching a word: `segment_video` can
take box prompts on given frames (one object id per box) instead of a text concept.

## HARD RULES
No deleting/moving files, no git. Tests never call the real API.

## Docs
- https://dev.meta.ai/docs/sam/segmenting — example "uploaded file, box and point prompts":
  the `input_text` part carries the prompt tokens, e.g.
  `<30f>1<|point;x=585;y=366;w=960;h=540|><75f>2<|box;x1=405;y1=337;x2=516;y2=420;w=960;h=540|>`,
  with `{"type": "input_video", "file_id": ...}`; `metadata.propagation_direction` default
  "both"; box/point prompts always return `one_bit` masks; max 16 prompted objects.
- Build the text with the installed library, never by hand:
  `meta_sam_parser.build_object_prompt(size=(w, h), objects=[PromptObject(id=1,
  prompts=[FramePrompt(frame=12, box=PromptBox(left, top, right, bottom))]), ...])`.
  `size` is the clip's (width, height); coordinates are ints inside it.

## Files to touch
- `app/meta_client.py` (only `segment_video` and small private helpers)
- `tests/test_sam_video.py`

## Do not touch
- everything else (Claude Code is rewriting `app/pipeline/motion.py` against this API now)

## What to build
New signature (keep the old call `segment_video(path, "back cover")` working):
```python
def segment_video(
    self, video_path: Path, concept: str | None = None, *,
    boxes: Sequence[tuple[int, int, tuple[int, int, int, int]]] = (),  # (object_id, frame, (l, t, r, b))
    size: tuple[int, int] | None = None,   # clip (width, height); required with boxes
    max_frames: int = 600,
) -> list[FrameTrack]:
```
- Exactly one of `concept` / `boxes` must be given (ValueError otherwise).
- With `boxes`: at most 16 objects; clamp each box inside `size`, ints, non-empty (skip and log
  a box that becomes empty; ValueError if none is left); `input_text` =
  `build_object_prompt(size=size, objects=...)`; `metadata` = `{"include_confidence": "true"}`
  plus nothing else (box prompts are always one_bit). Object ids in the answer are the ids we
  sent; `FrameTrack`/`TrackedObject` stay the same.
- Same budget/spend, upload/delete, retries and parsing as today (reuse, do not duplicate).

## Done when
- tests: the request text for 2 boxes equals what `build_object_prompt` returns; ids kept;
  concept+boxes or neither → ValueError; 17 boxes → ValueError; a box outside the clip is
  clamped; old concept calls unchanged (existing tests pass).
- `.venv/bin/pytest -q` all pass; `ruff check .` and `ruff format --check .` clean.
