# Task 004: transcribe
Branch: feat/transcribe
Owner: Muse Code

## Goal
Transcribe the job's `audio.wav` with `muse-voice-transcribe-1.0` and save the spoken turns
with their times in `transcript.json`. If there is no audio or nobody speaks, mark the job as silent.

## Why this matters for judging
Use of Meta AI tooling: the turn timestamps of Muse Voice Transcribe are one of our "unexpected
capabilities" (they become step cuts when the technician says "step" / "paso"). Impact: narrated
and silent videos must both work.

## Files to touch
- `app/meta_client.py` (add one method, change nothing else)
- `app/pipeline/transcribe.py`
- `tests/test_meta_client.py` (add tests)
- `tests/test_transcribe.py` (new)

## Do not touch
- Everything else. In particular `app/pipeline/ingest.py`, `app/pipeline/runner.py`,
  `app/jobs.py`, `app/schemas.py`, `pyproject.toml`, `.env*`.
- No new dependencies. The OpenAI SDK has no method for this endpoint: use `httpx` (allowed).
- Do not call the real API.

## What to build

### `MetaClient.transcribe(self, wav: Path, mode: str = "ENDPOINTING", language_bias: list[str] | None = None, keywords: list[str] | None = None) -> dict`
Docs: https://dev.meta.ai/docs/speech-to-text and https://dev.meta.ai/docs/api-reference/voice/schemas
1. `ValueError` if `wav` is bigger than 32 MB (33,554,432 bytes). `self.spend.check()`.
2. `POST {settings.meta_api_base}/asr/transcribe`, multipart with **two parts**, exactly:
   ```python
   request = {"model": settings.asr_model, "audioEncoding": "WAV", "mode": mode}
   if language_bias:
       request["languageBias"] = language_bias  # e.g. ["Spanish", "English"]
   if keywords:
       request["keywords"] = keywords  # e.g. ["step", "paso"]
   files = {
       "request": (None, json.dumps(request), "application/json"),
       "audio": (wav.name, f, "audio/wav"),  # open the file inside the retried function
   }
   headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
   ```
   Use `mode="ENDPOINTING"`: in the default `PUSH_TO_TALK` mode the `turns` list is **empty**.
3. Use an `httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0))`. Make it injectable for tests:
   add `http: Any | None = None` to `MetaClient.__init__` (default: build that client).
4. Go through `_with_retries`. So the same retry rules apply, convert inside the retried function:
   - `httpx.TimeoutException` → `raise openai.APITimeoutError(request=exc.request)`
   - status 429 → `raise openai.RateLimitError("asr status 429", response=resp, body=None)`
   - other status >= 400 → `raise openai.APIStatusError(f"asr status {status}", response=resp, body=None)`
5. Response (buffered JSON): `{"sessionId": str, "transcript": str, "audioDurationMs": int, "turns": [{"turnId": int, "startMs": int, "endMs": int, "transcript": str}]}`.
   Record spend with `asr_cost(audioDurationMs / 1000)` under the model `settings.asr_model`. Return the dict.
6. Never log the key, the audio or the transcript text.

### `app/pipeline/transcribe.py`
- `run(job_dir: Path, settings: Settings, client: MetaClient | None = None) -> dict` — the runner
  calls `run(job_dir, settings)`; tests pass a client with fakes.
  1. No `audio.wav` in `job_dir` → result `{"mode": "silent", "duration_s": 0.0, "transcript": "", "turns": []}`, no API call.
  2. Else `client.transcribe(job_dir / "audio.wav", mode="ENDPOINTING", language_bias=["Spanish", "English"], keywords=["step", "paso"])`.
  3. Convert turns to seconds: `{"start_s": startMs / 1000, "end_s": endMs / 1000, "text": transcript}`,
     drop turns whose text is empty after `.strip()`, sort by `start_s`.
  4. `mode` = `"narrated"` if the remaining turns have **at least 5 words in total**, else `"silent"`
     (a phone always records some noise; one stray word is not narration).
  5. Write the result **atomically** to `job_dir / "transcript.json"` (temp file in the same folder + `os.replace`) and return it.
     Result shape: `{"mode": "narrated", "duration_s": 42.5, "transcript": "...", "turns": [{"start_s": 1.2, "end_s": 3.4, "text": "Step one, remove the two screws"}]}`

## Done when
- `.venv/bin/pytest -q` passes; `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` are clean.
- Tests with a fake `http` object whose `post(url, headers=..., files=..., ...)` returns `httpx.Response(status, json=..., request=httpx.Request("POST", url))` or raises:
  1. Success → the request part JSON has `"mode": "ENDPOINTING"`, `"audioEncoding": "WAV"`, `"languageBias"`, `"keywords"`; the URL ends with `/asr/transcribe`; spend recorded = `asr_cost(seconds)`.
  2. 429 then 200 → 2 posts, result returned. 400 → `MetaError` after 1 post.
  3. `httpx.ReadTimeout` then 200 → result returned.
  4. A 33 MB file → `ValueError`, no post. Budget reached → `BudgetExceeded`, no post.
  5. `run` without `audio.wav` → silent, no call, `transcript.json` written.
  6. `run` with 3 turns (one empty) → 2 turns in seconds, sorted, `narrated`.
  7. `run` with one 2-word turn → `silent`.
- `"Authorization"` header value never appears in log output (use `caplog`).

## Notes
Make a tiny WAV for tests with the standard `wave` module (1 second of zeros, mono, 16-bit, 24000 Hz).
A 33 MB file for the size test: `path.write_bytes(b"\0" * (33 * 1024 * 1024))` in `tmp_path`.
