# Task 033: one helper for Spark JSON calls + one atomic-write helper for files
Branch: refactor/spark-call
Owner: Muse Code (muse-spark-1.3, high)

## Goal
Remove duplicated code WITHOUT changing behaviour: the 3 copies of "call Spark for strict JSON"
(analyze, identify, refine) use one helper, and the 6 copies of "write to a temp file, then
rename" use one helper. All 481 existing tests must keep passing (you may only update tests that
reference a function you removed or renamed).

## Why this matters for judging
Technical depth 20 %: one way to do each thing, smaller stages, easier to read and to trust.

## Files to touch
- `app/spark.py` (new), `tests/test_spark.py` (new)
- `app/artifacts.py` (add helpers only; keep every existing function as it is)
- `app/pipeline/analyze.py`, `app/pipeline/identify.py`, `app/pipeline/refine.py`
- `app/pipeline/ingest.py`, `app/pipeline/media.py`, `app/pipeline/frames.py`,
  `app/pipeline/perception.py`, `app/pipeline/overlay.py`
- in `perception.py` also: replace `_plural` and `_ARTICLES` with `app.text.plural` and
  `app.text.ARTICLES` / `drop_article` (same results for current inputs)
- tests of those modules ONLY if they import a removed/renamed private function

## Do not touch
- `app/meta_client.py`, `app/schemas.py`, `app/text.py`, `app/pipeline/runner.py`,
  `app/pipeline/proof.py`, `stepcheck.py`, `learn.py`, `publish.py`, routes, scripts
  (another task edits several of these right now)

## What to build
`app/artifacts.py` — add:
- `@contextmanager def atomic_path(dst: Path) -> Iterator[Path]`: yields a temp path in the same
  folder that KEEPS the suffix (ffmpeg, cv2 and Pillow pick the format from it):
  `dst.with_name(f".{dst.stem}.tmp{dst.suffix}")`. Creates the parent folder. On normal exit
  `os.replace(tmp, dst)`; on any exception delete the temp file and re-raise.
- `write_bytes_atomic(dst: Path, data: bytes) -> None` and
  `write_text_atomic(dst: Path, text: str) -> None` built on `atomic_path`.
Use `atomic_path` in the 6 places: `ingest.py:~299`, `media.py:~58`, `frames.py:~378` and `~431`,
`perception.py:~223`, `overlay.py:~260`. Same files written, same names.

`app/spark.py`:
```python
class SparkAnswerError(Exception):   # Spark's text is not valid JSON

def json_format(name: str, schema: dict) -> dict:
    # {"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}}

def image_block(path: Path) -> dict:
    # {"type": "input_image", "image_url": "data:image/<png|jpeg>;base64,..."} (mime from suffix)

def ask_json(
    client, settings, *, name: str, schema: dict, prompt: str,
    images: Sequence[Path] = (), video: Path | None = None,
    raw_path: Path | None = None, max_output_tokens: int = 4000,
    timeout_s: float | None = None, retry_timeouts: bool = True,
) -> Any:
    # 1. if video: file_id = client.upload_file(video); always client.delete_file(file_id) in finally
    # 2. input = [{"role": "user", "content": [input_text, *image blocks, input_file?]}]
    #    (exact same block shapes as analyze/identify/refine build today)
    # 3. response = client.respond(model=settings.spark_model, input=..., text=json_format(...),
    #    max_output_tokens=..., timeout_s=..., retry_timeouts=...)
    # 4. text = response.output_text or ""; if raw_path: artifacts.write_text_atomic(raw_path, text)
    # 5. return json.loads(text); invalid -> SparkAnswerError(f"Spark returned invalid JSON for {name}")
```
Then in each stage keep its public functions and its own error class:
- analyze: `parse_analysis` keeps working; `run` uses `ask_json(..., video=video_path,
  raw_path=job_dir / "analysis_raw.txt", max_output_tokens=MAX_OUTPUT_TOKENS,
  timeout_s=ANALYZE_TIMEOUT_S, retry_timeouts=False)` and turns SparkAnswerError / validation
  errors into `AnalyzeError("Spark returned an invalid analysis")` exactly as today.
- identify: same idea with `images=paths`, `raw_path=job_dir / "identify_raw.txt"`.
- refine: `refine_step` uses `ask_json(..., video=clip_path, ...)` (no raw file, as today) and
  keeps its sanity checks and RefineError messages.
- `build_input` functions: keep them if tests use them, as thin wrappers, or update those tests.

## Done when
- `tests/test_spark.py`: json_format shape; image_block png/jpg; ask_json with a fake client:
  text-only, images, video (upload + delete called even when respond raises), raw file written
  even for invalid JSON, SparkAnswerError on bad JSON; atomic_path: success replaces, exception
  leaves no temp file and keeps the old file, suffix kept.
- `grep -rn "os.replace" app | grep -v artifacts.py` → only `app/meta_client.py` lines.
- `grep -rn '"json_schema"' app/pipeline` → nothing (all through `app/spark.py`).
- `.venv/bin/pytest -q` all pass; `ruff check .` and `ruff format --check .` clean.
