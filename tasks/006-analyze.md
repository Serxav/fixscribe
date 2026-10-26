# Task 006: analyze
Branch: feat/analyze
Owner: Muse Code

## Goal
The analyze stage: send the job video (plus the spoken turns and the voice step cuts, if any) to
`muse-spark-1.3` with a strict JSON schema, and save its answer as `analysis.json`.

## Why this matters for judging
Use of Meta AI tooling + Impact: this is the call that turns a phone video into repair steps. It
combines what Spark sees in the video with what Muse Voice heard, and uses structured output so
the guide never breaks on bad JSON in the live demo.

## Files to touch
- `app/pipeline/analyze.py`
- `tests/test_analyze.py` (new)

## Do not touch
- Everything else. In particular `prompts/analyze_v1.md` and `app/schemas.py` (Claude Code wrote
  the prompt and the schema: use them, do not change them), `app/meta_client.py`,
  `app/pipeline/guide.py`, `app/pipeline/runner.py`, `pyproject.toml`, `.env*`.
- No new dependencies. Do not call the real API.

## Input files (in `job_dir`, written by earlier stages)
- `video.mp4` (required) and `ingest.json` (required): `{"duration_s": 42.0, ...}`
- `transcript.json` (optional): `{"mode": "narrated", "turns": [{"start_s": 1.2, "end_s": 3.4, "text": "..."}], ...}`
- `scenes.json` (optional): `{"source": "voice", "segments": [{"start_s": 1.2, "end_s": 15.0}], ...}`

## What to build (`app/pipeline/analyze.py`)
- `class AnalyzeError(Exception)`.
- `PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "analyze_v1.md"`
- `TEXT_FORMAT = {"format": {"type": "json_schema", "name": "repair_analysis", "schema": ANALYSIS_JSON_SCHEMA, "strict": True}}`
  (`from app.schemas import ANALYSIS_JSON_SCHEMA, Analysis`). Docs: https://dev.meta.ai/docs/structured-output
  (`text.format` is the Responses API parameter) and https://dev.meta.ai/docs/api-reference/responses/schemas.
- `MAX_OUTPUT_TOKENS = 16000` (Spark reasons before answering; reasoning shares this budget).
- `build_prompt(duration_s: float, mode: str, turns: list[dict], segments: list[dict]) -> str` —
  read `PROMPT_PATH` and replace exactly these 4 placeholders (plain `str.replace`, no `format`):
  - `<<DURATION_S>>` → `f"{duration_s:.1f}"`
  - `<<MODE>>` → `mode` (`"narrated"` or `"silent"`)
  - `<<TURNS>>` → one line per turn `- [1.2–3.4 s] Step one, remove the screws` (times with 1 decimal),
    or `- (none)` if empty
  - `<<SEGMENTS>>` → one line per segment `- step 1: 1.2–15.0 s`, or `- (none)` if empty
- `build_input(prompt: str, file_id: str) -> list[dict]` — same shape as in `scripts/first_call.py`:
  one user message with an `input_text` block (the prompt) and an `input_file` block (`file_id`).
- `parse_analysis(text: str) -> Analysis` — `json.loads` then `Analysis.model_validate`. Empty text,
  bad JSON or a validation error → `AnalyzeError("Spark returned an invalid analysis")`.
- `run(job_dir: Path, settings: Settings, client: MetaClient | None = None) -> Analysis`:
  1. Missing `video.mp4` or `ingest.json` → `AnalyzeError` naming the file.
  2. Read `transcript.json` if it exists (else mode `"silent"`, no turns) and `scenes.json` if it
     exists (use its `segments` only when `source == "voice"`).
  3. `client = client or MetaClient(settings)`. `file_id = client.upload_file(job_dir / "video.mp4")`.
  4. In `try/finally` (finally: `client.delete_file(file_id)`):
     `response = client.respond(model=settings.spark_model, input=build_input(prompt, file_id), max_output_tokens=MAX_OUTPUT_TOKENS, text=TEXT_FORMAT)`.
  5. `analysis = parse_analysis(response.output_text)`.
  6. Write `analysis.json` atomically (temp file in the same folder + `os.replace`) with
     `analysis.model_dump(mode="json")`, and return `analysis`.
  Do not catch `MetaError` / `BudgetExceeded`: the runner turns them into a clear job error.

## Done when
- `.venv/bin/pytest -q` passes; `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` are clean.
- Tests with a fake client (`files.create`, `files.delete`, `responses.create`, like in
  `tests/test_meta_client.py` and `tests/test_first_call.py`), `Settings(model_api_key="", data_dir=tmp_path)`,
  and a few bytes written to `video.mp4` (no real video needed):
  1. Narrated job → the `responses.create` kwargs contain `text == TEXT_FORMAT`,
     `max_output_tokens == 16000`, and the prompt text contains a turn line and `- step 1:`;
     `analysis.json` is written and validates with `Analysis`.
  2. Silent job without `transcript.json` / `scenes.json` → the prompt contains `silent` and `- (none)` twice.
  3. `scenes.json` with `source: "none"` → segments are not used (`- (none)`).
  4. The prompt has no `<<` left after `build_prompt`.
  5. Spark returns broken JSON → `AnalyzeError`, and `files.delete` was still called.
  6. `responses.create` raises a 400 → `MetaError`, and `files.delete` was still called.
  7. Missing `video.mp4` → `AnalyzeError` mentioning `video.mp4`, no upload.

## Notes
A valid fake answer is the `answer` dict in `tests/test_analysis_schema.py`; return it as
`SimpleNamespace(output_text=json.dumps(answer), usage=<fake usage>)`.
