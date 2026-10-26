# Task 002: first-call
Branch: feat/first-call
Owner: Muse Code

## Goal
A script that makes ONE real call to `muse-spark-1.3` with a short repair video and says how
close its step times are to the times Sergi wrote by hand.

## Why this matters for judging
Use of Meta AI tooling + Technical depth: it proves with numbers that Muse Spark 1.3 can find step times in a real repair video, the first figure for `eval/` and the demo.

## Files to touch
- `app/meta_client.py` (add two methods, change nothing else)
- `scripts/__init__.py` (new, empty)
- `scripts/first_call.py` (new)
- `tests/test_meta_client.py` (add tests)
- `tests/test_first_call.py` (new)

## Do not touch
- Everything else. In particular `app/schemas.py`, `app/jobs.py`, `app/pipeline/`, `app/config.py`,
  `pyproject.toml`, `.env`, `.env.example`, `samples/`.
- No new dependencies.
- **Do not run the real call.** Sergi runs it once after the review. Your tests use fakes only.

## What to build

### `app/meta_client.py`: two new methods on `MetaClient`
- `upload_file(self, path: Path, expires_seconds: int = 86400) -> str`
  - `ValueError` if the suffix is not `.mp4` or the file is bigger than 1 GiB (1,073,741,824 bytes).
  - Calls `self._client.files.create(purpose="user_data", file=f, expires_after={"anchor": "created_at", "seconds": expires_seconds})`
    through `_with_retries`. **Open the file inside the function you pass to `_with_retries`**
    (`with open(path, "rb") as f: ...`), so a retry sends the whole file again, not an
    already-read handle.
  - Returns the file id (`file.id`, it starts with `file-`). Uploading is free: do not touch the
    spend counter.
- `delete_file(self, file_id: str) -> None` — `self._client.files.delete(file_id)` through
  `_with_retries`. If it fails, log a warning and do not raise (cleanup must never break a run).

### `scripts/first_call.py`
Usage: `.venv/bin/python scripts/first_call.py samples/<name>.mp4`
Expected times file: `samples/<name>.expected.json` (Sergi writes it):
```json
{"steps": [{"title": "Remove back cover", "start_s": 3.0, "end_s": 15.5}]}
```

Functions (pure ones are tested):
- `video_seconds(path: Path) -> float` — run `ffprobe -v error -show_entries format=duration -of csv=p=0 <path>` with `subprocess.run(..., check=True, capture_output=True, text=True, timeout=30)`.
- `build_input(file_id: str) -> list[dict]` — exactly this shape (from https://dev.meta.ai/docs/video-understanding):
  ```python
  [
      {
          "role": "user",
          "content": [
              {"type": "input_text", "text": PROMPT},
              {"type": "input_file", "file_id": file_id},
          ],
      }
  ]
  ```
- `PROMPT: str` — ask for the repair steps as JSON only:
  `{"steps": [{"title": str, "start_s": float, "end_s": float}]}`, seconds from the start of
  the video, one entry per step, a new step every time the technician starts a new action or
  says "step" / "paso". English titles.
- `parse_steps(text: str) -> list[dict]` — accepts plain JSON or JSON inside a ```` ```json ```` fence.
  Returns the `steps` list. Raises `ValueError("model did not return valid steps JSON")` otherwise.
  Every step must have `title` (str), `start_s` and `end_s` (numbers, `0 <= start_s < end_s`).
- `compare_steps(found: list[dict], expected: list[dict], tolerance_s: float = 2.0) -> dict` —
  match by position (1st with 1st, …). Returns:
  ```python
  {
      "expected": 4,
      "found": 3,
      "hits": 2,
      "rows": [
          {"index": 1, "title": "...", "start_error_s": 0.5, "end_error_s": 1.0, "hit": True},
          ...,
      ],
  }
  ```
  A row is a hit when both errors are `<= tolerance_s`. Steps missing on either side get a row
  with errors `None` and `hit: False`.
- `main(argv: list[str] | None = None) -> int`:
  1. No argument → print usage, return 2. Video or `.expected.json` missing → clear message, return 1.
  2. `get_settings()`. Empty `model_api_key` → print "MODEL_API_KEY is not set", return 1.
     Never print the key.
  3. `video_seconds` > `settings.max_video_seconds` → message, return 1.
  4. `client = MetaClient(settings)`; print spend before (`client.spend.total()`).
  5. `file_id = client.upload_file(path)`; then in `try/finally` (finally: `client.delete_file(file_id)`):
     `response = client.respond(model=settings.spark_model, input=build_input(file_id), max_output_tokens=8000)`.
  6. Save `response.output_text` and the comparison to `data/first_call/<name>.json`
     (use `app.jobs`-style atomic write: temp file + `os.replace`).
  7. Print a table (index, title, start error, end error, hit), the line
     `Steps within ±2.0 s: 2/4`, the cost of this call and the spend after. Return 0.
  8. `BudgetExceeded` or `MetaError` → print the message, return 1 (no traceback).
- End of file: `if __name__ == "__main__": raise SystemExit(main())`

## Docs
- Video input and the `input_file` block: https://dev.meta.ai/docs/video-understanding
- Files API (purpose `user_data`, 1 GiB max, `expires_after` 3600–2592000 s, delete): https://dev.meta.ai/docs/file-handling
- Errors: https://dev.meta.ai/docs/error-handling

Note from the docs: Muse Spark 1.3 audio understanding is "currently not fully supported".
This first call checks the **video** only; narration is handled later by `muse-voice-transcribe-1.0`.

## Done when
- `.venv/bin/pytest -q` passes; `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` are clean.
- `.venv/bin/python scripts/first_call.py` → prints usage, exit code 2 (`echo $?`).
- New tests (fakes only, no network):
  1. `upload_file` returns the id from a fake `files.create`; `.mov` → `ValueError` without calling the fake.
  2. `upload_file`: 503 then success → 2 calls, the file is read fully both times
     (record `len(kwargs["file"].read())` in the fake).
  3. `delete_file` with a fake that raises 404 → no exception.
  4. `parse_steps`: plain JSON, fenced JSON, and broken text → `ValueError`; `end_s <= start_s` → `ValueError`.
  5. `compare_steps`: exact match → all hits; 3 found vs 4 expected → `hits` counts right and the
     last row has `None` errors; an error of 2.5 s → not a hit.
  6. `main([])` → 2; `main(["missing.mp4"])` → 1.

## Notes
Make a fake `files` object the same way as `FakeResponses` in `tests/test_meta_client.py`
(`create(**kwargs)` and `delete(file_id)`). In `test_first_call.py` import with
`from scripts.first_call import parse_steps, compare_steps, main`.
