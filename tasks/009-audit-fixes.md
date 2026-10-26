# Task 009: audit-fixes (meta client and transcribe)
Branch: fix/audit-meta-client
Owner: Muse Code (muse-wonder-1.0)

## Goal
Fix the money and failure problems found in the audit (`tasks/AUDIT.md`) in `app/meta_client.py`
and `app/pipeline/transcribe.py`: long calls get their own timeout, paid calls are never retried
blindly after a timeout, Retry-After is capped, connection errors are retried, a corrupt
`spend.json` never blocks or resets the budget, and a partial ASR answer never crashes a job.

## Why this matters for judging
Technical depth + Demo: a 5-minute video must not time out four times and pay four times, and one
broken file must not stop every job during the live demo. The audit itself (Wonder reviewing
code written by Spark) is part of our "built with Muse Code" story.

## Files to touch
- `app/meta_client.py`
- `app/pipeline/transcribe.py`
- `app/pipeline/analyze.py` (only the `client.respond(...)` call)
- `tests/test_meta_client.py`, `tests/test_transcribe.py`, `tests/test_analyze.py`

## Do not touch
- Everything else. In particular `app/schemas.py`, `app/pipeline/guide.py`, `app/pipeline/runner.py`,
  `app/jobs.py`, `app/routes/`, `prompts/`, `pyproject.toml`, `.env*`. No new dependencies.
- Do not call the real API (tests have a network block in `tests/conftest.py`).

## What to change

### A. Per-call timeout and no blind retry of paid timeouts (audit C2 / W8)
- `MetaClient.respond(..., timeout_s: float | None = None, retry_timeouts: bool = True, **kwargs)`:
  if `timeout_s` is set, pass `timeout=httpx.Timeout(timeout_s, connect=10.0)` to
  `responses.create` (the OpenAI SDK accepts a per-request `timeout`).
- `_with_retries(self, fn, retry_timeouts: bool = True)`: catch `openai.APITimeoutError` **before**
  `openai.APIConnectionError` (it is a subclass). If `retry_timeouts` is False, raise at once
  `MetaError(f"meta api timed out", status_code=None)` — no sleep, no second attempt (the server
  may already have billed the first one).
- `app/pipeline/analyze.py`: add `ANALYZE_TIMEOUT_S = 600.0` and call
  `client.respond(..., timeout_s=ANALYZE_TIMEOUT_S, retry_timeouts=False)`. Nothing else in that file.

### B. ASR timeout (audit C7)
- `ASR_TIMEOUT_S = 300.0`. In `transcribe`, pass `timeout=httpx.Timeout(ASR_TIMEOUT_S, connect=10.0)`
  to `self._http.post(...)`. ASR timeouts stay retryable (it is cheap and only billed on success).

### C. Cap Retry-After (audit W5)
- `MAX_RETRY_AFTER_S = 30.0`. A server `Retry-After` larger than that is clamped to 30 s; a negative
  one is treated as missing.

### D. Retry connection errors in ASR (audit W7)
- Inside the retried function of `transcribe`: `httpx.TimeoutException` → `openai.APITimeoutError(request=exc.request)`
  (as now), and any other `httpx.TransportError` → `openai.APIConnectionError(message=str(exc), request=exc.request)`.
  Keep the timeout check first (`ReadTimeout` is also a `TransportError`).

### E. Corrupt `spend.json` never blocks nor resets the budget (audit W4)
- `SpendCounter.add` also appends one line to `spend.log` in the same folder, inside the same lock,
  before rewriting `spend.json`: `{"model": "...", "usd": 0.0123, "at": "<ISO UTC time>"}` + `"\n"`
  (open with `"a"`, write, `flush()`, `os.fsync()`).
- `SpendCounter.total()`: read `spend.json`; if it is missing **and** `spend.log` is missing → `0.0`.
  If `spend.json` is unreadable or not valid (`ValueError`, `TypeError`, `KeyError`, `OSError`
  other than missing), log `logger.error("spend.json is corrupt, rebuilding total from spend.log")`
  and return the sum of `usd` over the valid lines of `spend.log` (skip broken lines).
- `SpendCounter.add`: same fallback when reading the old totals (rebuild `total_usd`, `calls` and
  `by_model` from `spend.log`), then write a fresh valid `spend.json`. A paid call must never fail
  because of the spend file.
- Never reset the total to 0 when there is history: the budget check must keep working.

### F. Partial ASR answers (audit C6 / W6)
- `transcribe`: a 200 whose body is not JSON, or not a dict → still record spend (from the WAV),
  then raise `MetaError("asr returned an invalid answer")`.
- If `audioDurationMs` is missing or not a number, compute the duration from the WAV with the
  standard `wave` module (`frames / rate`) and use that for `asr_cost`. Put the value you used back
  in the returned dict as `audioDurationMs` (int ms).
- `app/pipeline/transcribe.py`: skip (do not crash on) a turn that lacks `startMs`, `endMs` or
  `transcript`, or whose times are not numbers; log a warning with the turn index only (never the text).
  If `turns` is missing or not a list, treat it as `[]`.

## Done when
- `.venv/bin/pytest -q` passes; `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` are clean.
- New tests (fakes only):
  1. `respond(timeout_s=600)` → the fake `responses.create` received `timeout` with `read == 600`.
  2. `respond(retry_timeouts=False)` + `APITimeoutError` → `MetaError` after **1** call and no sleep;
     with the default (`True`) a timeout then success still works.
  3. Analyze passes `timeout_s=600.0` and `retry_timeouts=False` (check the fake client's kwargs / call).
  4. `Retry-After: 86400` → `sleep` called with `30.0`. `Retry-After: -5` → fallback backoff (< 2.0).
  5. ASR: `httpx.ConnectError` then 200 → 2 posts, result returned. ASR post receives `timeout.read == 300`.
  6. Corrupt `spend.json` (`"{"`) with a `spend.log` of two lines (1.0 and 2.0) → `total() == 3.0`;
     `add(...)` works and rewrites a valid `spend.json` with the new total; `check()` still raises
     `BudgetExceeded` when the rebuilt total is over budget. A broken line in `spend.log` is skipped.
  7. ASR 200 without `audioDurationMs` and a 2-second WAV → spend recorded = `asr_cost(2)`.
     ASR 200 with body `"not json"` → `MetaError`, spend recorded.
  8. `transcribe.run` with one turn missing `startMs` and one good turn → 1 turn kept, no crash.

## Notes
Keep the code simple and readable (Sergi is a student and must understand it). Short helper
functions with docstrings are better than one long method.
