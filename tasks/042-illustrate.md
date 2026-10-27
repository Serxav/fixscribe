# Task 042: illustrate stage — Muse Image draws an exploded-view illustration per step
Branch: feat/illustrate
Owner: Muse Code (muse-spark-1.3, high). Web tools ON only for dev.meta.ai docs.

## Goal
For the steps that remove a part, Muse Image turns the step's real keyframe into a clean
technical "exploded view" illustration (the part lifted off, fasteners floating above their
holes, numbered). Saved as `steps/NN_illustration.webp` and listed in `illustrations.json`.
Targets the Best Creative Build prize (needs Muse Image).

## HARD RULES
No deleting/moving files, no git. Tests never call the real API. Every field from the docs.

## Docs
- https://dev.meta.ai/docs/image-generation — `POST /v1/images/edits`, model `muse-image-1.0`.
  Raw JSON body: `{"model", "prompt", "images": [{"image_url": "data:image/jpeg;base64,..."}],
  "n": 1, "output_format": "webp"}`; response `data[0].b64_json`. $0.01 per returned image
  (`PRICES["muse-image-1.0"]["per_image"]` already exists). Do NOT send `mask`, `moderation`,
  `input_fidelity`. `400 content_policy_violation` → skip that step (note), not a crash.
  503 retryable (reuse the client's retry helpers), 500 not.

## Files to touch
- `app/meta_client.py`: add `edit_image(image_path: Path, prompt: str) -> bytes` (budget check
  before, spend after success, retries like the other calls; JSON body via the existing httpx
  usage of `transcribe`, or the OpenAI SDK `images.edit` if the client already exposes it —
  choose the simplest that follows the docs and write which under DUDAS).
- `app/pipeline/illustrate.py` (new), `prompts/illustrate_v1.md` (new)
- `tests/test_illustrate.py` (new) and tests for `edit_image` in `tests/test_meta_client.py`

## Do not touch
- `app/schemas.py`, `runner.py`, `publish.py`, web, other stages. Claude Code adds the contract
  `Illustrations` to schemas and wires the stage; until then use these exact shapes in a local
  pydantic model inside `illustrate.py` named `Illustrations` with `FILENAME =
  "illustrations.json"`, fields `steps: list[StepIllustration]` (`index: int`, `image: str`,
  `prompt: str`) and `notes: list[str]` — Claude Code will move it to schemas unchanged.

## What to build
- `MAX_ILLUSTRATIONS = 4`. Steps chosen: those with a `target_part` and (fasteners or an action in
  remove/unscrew/unclip/pry/open/disconnect), in step order, at most MAX_ILLUSTRATIONS.
- Input image: the step keyframe `job_dir / step.image` (`steps/NN.jpg`, from frames.json /
  plan). Missing image → skip with a note.
- Prompt from `prompts/illustrate_v1.md` with `<<OBJECT>>` (identity.object_name or plan.device),
  `<<PART>>`, `<<FASTENERS>>` ("4 screws" via `app.text.plural`), `<<ACTION>>`: a clean white
  background technical illustration in the style of a product manual: isometric exploded view of
  THIS object as in the photo, the part lifted along its removal direction, fasteners floating
  above their holes with small numbers 1..N, thin dashed motion guides, soft shadows, no text
  labels other than the numbers, no logos, no brand names.
- `run(job_dir, settings, client=None)`: one `client.edit_image` per chosen step; any per-step
  failure (policy block, error) → note and continue; BudgetExceeded → note and stop; write
  `illustrations.json`; return it.

## Done when
- tests: step selection; prompt filling; run with a fake client writes the .webp files and the
  json; a policy-blocked step is skipped with a note; budget stop; `edit_image` builds the right
  JSON body (model, prompt, images[0].image_url data URL, n=1, output_format webp), adds
  0.01 $ spend, refuses when the budget is reached, decodes b64.
- `.venv/bin/pytest -q` all pass; `ruff check .` and `ruff format --check .` clean.
