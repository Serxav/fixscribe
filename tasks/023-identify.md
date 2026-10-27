# Task 023: identify stage (what is FixScribe looking at?)
Branch: feat/identify
Owner: Muse Code (muse-spark-1.3, high)

## Goal
A new pipeline stage `identify` that looks at a few frames of the video (plus the first spoken
words, if any) and writes `identity.json`: what the object is, its category, the task, visible
hazards, skill level, language and evidence. Every later stage will choose its behaviour from it.

## Why this matters for judging
FixScribe is now universal (phones, washing machines, chairs, cars, taps...). "First detect what
it is, then the magic": this stage is the first thing the demo shows (Impact 30 %) and a clean
multimodal Spark call with strict JSON (Use of Meta AI 25 %, Technical depth 20 %).

## Files to touch
- `app/pipeline/identify.py` (new)
- `prompts/identify_v1.md` (new)
- `tests/test_identify.py` (new)

## Do not touch
- `app/schemas.py` (Identity and IDENTITY_JSON_SCHEMA already exist: use them as they are)
- `app/pipeline/runner.py` (Claude Code wires the stage in)
- `app/meta_client.py`, `app/pipeline/media.py`, every other file

## What to build
In `app/pipeline/identify.py`:
- `VERSION = "1"`, `N_FRAMES = 4`, `MAX_SIDE = 768`, `MAX_OUTPUT_TOKENS = 4000`,
  `IDENTIFY_TIMEOUT_S = 120.0`, `MAX_TRANSCRIPT_CHARS = 1500`.
- `class IdentifyError(Exception)`.
- `frame_times(duration_s: float, n: int = N_FRAMES) -> list[float]`: evenly spread inside the
  video, never at the very start or end: for n=4 → 10 %, 36.7 %, 63.3 %, 90 % of the duration
  (`duration * (0.1 + 0.8 * i / (n - 1))`); n=1 → the middle. Raise ValueError if duration <= 0.
- `build_prompt(transcript_text: str) -> str`: read `prompts/identify_v1.md`, replace
  `<<TRANSCRIPT>>` with the first `MAX_TRANSCRIPT_CHARS` characters of the transcript, or
  `(no speech)` when empty.
- `image_data_url(path: Path) -> str`: PNG bytes → `data:image/png;base64,...`.
- `build_input(prompt: str, images: list[Path]) -> list[dict]`: one user message whose content is
  `[{"type": "input_text", "text": prompt}]` followed by one
  `{"type": "input_image", "image_url": <data url>}` per image (same shape as
  `app/meta_client.py` line ~496 uses for SAM).
- `parse_identity(text: str) -> Identity`: `json.loads` + `Identity.model_validate`; any error →
  `IdentifyError("Spark returned an invalid identity")` (chain the cause).
- `run(job_dir: Path, settings: Settings, client: MetaClient | None = None) -> Identity`:
  1. `ingest = artifacts.load(job_dir, IngestInfo)`; transcript via `artifacts.load_optional`.
  2. Frames from the ORIGINAL upload at native colour handling:
     `media.extract_stills(find_original(job_dir), ingest.source, frame_times(...), job_dir /
     "identify", max_side=MAX_SIDE)`. If `ingest.source` is None, raise
     `IdentifyError("ingest has no source info")` (never invent a SourceVideo).
     `find_original` is in `app/pipeline/ingest.py`.
  3. One `client.respond(model=settings.spark_model, input=..., max_output_tokens=MAX_OUTPUT_TOKENS,
     text={"format": {"type": "json_schema", "name": "repair_identity",
     "schema": IDENTITY_JSON_SCHEMA, "strict": True}}, timeout_s=IDENTIFY_TIMEOUT_S)`.
  4. Write the raw answer to `identify_raw.txt` (like analyze), parse, `artifacts.save`, return.
  5. Delete the `identify/` stills folder at the end (in `finally`): they are only for the call.

`prompts/identify_v1.md` (English, short, < 60 lines). It must say:
- You see N frames of one repair video, in time order, plus the first spoken words.
- Decide the object (most specific name you can justify), category, brand and model ONLY if
  readable or said (else ""), the task, the problem if shown or said.
- Hazards: list every one that applies to this object or task, even if not visible yet
  (a washing machine → mains_voltage, pressurized_water, heavy_part). Never omit a hazard to be
  nice; when unsure, include it.
- `language`: ISO 639-1 of the speech, "en" if silent.
- `evidence`: 1–4 short facts from the frames or the speech ("logo 'Bosch' on the door at frame 2").
- `confidence` 0..1; if the frames are blurry or show only hands, say so in evidence and lower it.
- Then `<<TRANSCRIPT>>`.

## Docs
- Responses API with images: https://dev.meta.ai/docs (Responses → input types). Fields used:
  `input_text`, `input_image` with `image_url` as a data URL, `text.format` json_schema strict.
  Up to 50 images per request; do not add any other field (there is no `detail`).

## Done when
- `.venv/bin/pytest -q tests/test_identify.py` passes with at least these tests (mock the client,
  never the network; build a tiny video with `tests/video_factory.py` and run real `ingest.run`
  first, like `tests/test_frames.py` does, or write ingest.json by hand if that is simpler):
  1. `frame_times(100)` → `[10.0, 36.67, 63.33, 90.0]` (approx), `frame_times(10, 1)` → `[5.0]`,
     `frame_times(0)` raises.
  2. `build_prompt("")` contains `(no speech)`; a 5000-char transcript is cut to 1500.
  3. `build_input` puts the text first and N `input_image` blocks with `data:image/png;base64,`.
  4. `run` with a fake client returning valid JSON writes `identity.json` that loads as Identity,
     sends exactly N_FRAMES images, uses `text.format.strict == True`, and removes `identify/`.
  5. `run` with invalid JSON raises IdentifyError, still writes `identify_raw.txt`, still removes
     `identify/`.
  6. `confidence: 85` in the answer is stored as 0.85 (the schema validator already does this).
- `.venv/bin/pytest -q` (all) passes, `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .`
  are clean.

## Notes
- Cost: 4 images at 768 px ≈ 4 × ~800 tokens + prompt ≈ 0.005 $ per job. Do not add retries of
  your own; `MetaClient` already handles 429 and timeouts.
- The stage will be optional in the runner: if it fails, later stages use the generic profile.
  So raise clear errors; never return a fake Identity.
- Read `app/pipeline/analyze.py` as the model for structure and style.
