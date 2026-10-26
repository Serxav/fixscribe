# Task 001: meta-client
Branch: feat/meta-client
Owner: Muse Code

## Goal
One small client in `app/meta_client.py` that calls the Meta Responses API with retries and a
spend counter saved in `data/spend.json`. No real API call in this task: everything is tested
with a fake client.

## Files to touch
- `app/config.py`
- `app/meta_client.py`
- `tests/test_config.py` (new)
- `tests/test_meta_client.py` (new)

## Do not touch
- Everything else. In particular: `app/schemas.py`, `app/jobs.py`, `app/main.py`,
  `pyproject.toml`, `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.env`, `.env.example`.
- Do not add dependencies. Use only: `openai`, `httpx`, `python-dotenv` and the standard library.

## What to build

### `app/config.py`
- `@dataclass(frozen=True) class Settings` with these fields (env name in brackets):
  - `model_api_key: str` [`MODEL_API_KEY`] — declare it with `field(repr=False)` so the key never
    appears in `repr()` or logs.
  - `meta_api_base: str = "https://api.meta.ai/v1"` [`META_API_BASE`]
  - `spark_model: str = "muse-spark-1.3"` [`SPARK_MODEL`]
  - `wonder_model: str = "muse-wonder-1.0"` [`WONDER_MODEL`]
  - `sam_model: str = "sam-3.1"` [`SAM_MODEL`]
  - `asr_model: str = "muse-voice-transcribe-1.0"` [`ASR_MODEL`]
  - `max_video_seconds: int = 600` [`MAX_VIDEO_SECONDS`]
  - `enable_inspector: bool = True` [`ENABLE_INSPECTOR`] — "true"/"1"/"yes" → True, anything else → False
  - `daily_job_limit: int = 20` [`DAILY_JOB_LIMIT`]
  - `budget_usd: float = 120.0` [`BUDGET_USD`]
  - `data_dir: Path = Path("data")` [`DATA_DIR`, optional]
- `get_settings() -> Settings`: calls `load_dotenv(override=False)`, then reads `os.environ`.
  A missing `MODEL_API_KEY` gives `model_api_key=""` (tests and the web app must still start).

### `app/meta_client.py`
- `PRICES: dict[str, dict[str, float]]` in USD, copied from
  https://dev.meta.ai/docs/pricing-rate-limits (put this link in a comment above the dict):

  | model | key | value |
  |---|---|---|
  | `muse-spark-1.3` | `input_per_m` / `cached_input_per_m` / `output_per_m` | 1.25 / 0.15 / 4.25 |
  | `muse-wonder-1.0` | `input_per_m` / `cached_input_per_m` / `output_per_m` | 4.00 / 0.20 / 20.00 |
  | `sam-3.1` | `per_image` / `per_video_frame` | 0.0025 / 0.0002 (= $2.50 per 1,000 images, $0.20 per 1,000 frames) |
  | `muse-voice-transcribe-1.0` | `per_hour` | 0.18 (metered in whole seconds) |
  | `muse-image-1.0` | `per_image` | 0.01 |

- `class BudgetExceeded(Exception)` — raised **before** a call when the spend is already at or over the budget.
- `class MetaError(Exception)` — has `status_code: int | None`. Raised for a non-retryable error,
  or when retries are used up. Its message must never contain the API key.

- `token_cost(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float`
  `cached_tokens` is a **subset** of `input_tokens` (https://dev.meta.ai/docs/prompt-caching), so:
  `(input_tokens - cached_tokens) * input + cached_tokens * cached_input + output_tokens * output`, all / 1,000,000.
  Unknown model → `ValueError`.
- `sam_cost(images: int = 0, video_frames: int = 0) -> float`
- `asr_cost(seconds: float) -> float` — round seconds **up** to a whole second (`math.ceil`), then `/ 3600 * 0.18`.

- `class SpendCounter`:
  - `__init__(self, path: Path, budget_usd: float)`
  - `total(self) -> float` — 0.0 if the file does not exist.
  - `check(self) -> None` — raises `BudgetExceeded` if `total() >= budget_usd`.
  - `add(self, model: str, usd: float) -> float` — adds and returns the new total.
  - File format of `data/spend.json`:
    `{"total_usd": 1.455, "calls": 1, "by_model": {"muse-spark-1.3": 1.455}}`
  - **Atomic write**: create the parent folder, write to a temp file in the same folder
    (`tempfile.NamedTemporaryFile(dir=..., delete=False)`), then `os.replace(tmp, path)`.
  - Several jobs can run at once: hold an exclusive lock on `spend.lock` (same folder) with
    `fcntl.flock` around read + write in `add`.

- `class MetaClient`:
  - `__init__(self, settings: Settings, client: Any | None = None, sleep: Callable[[float], None] = time.sleep)`
    If `client` is None, build it exactly like the docs (https://dev.meta.ai/docs/sdks):
    `OpenAI(api_key=settings.model_api_key, base_url=settings.meta_api_base, max_retries=0, timeout=httpx.Timeout(120.0, connect=10.0))`.
    `max_retries=0` because **we** do the retries. The spend counter is
    `SpendCounter(settings.data_dir / "spend.json", settings.budget_usd)`.
  - `respond(self, *, model: str, input: Any, max_output_tokens: int = 4000, **kwargs) -> Any`
    1. `ValueError` if `model` is not in `PRICES` or if `max_output_tokens < 4000` (AGENTS.md §8).
    2. `self.spend.check()`
    3. Call `self.client.responses.create(model=model, input=input, max_output_tokens=max_output_tokens, **kwargs)` through `_with_retries`.
    4. Read `response.usage.input_tokens`, `response.usage.input_tokens_details.cached_tokens`,
       `response.usage.output_tokens` (https://dev.meta.ai/docs/api-reference/responses/schemas),
       compute `token_cost` and `self.spend.add(model, cost)`.
    5. Return the response object unchanged.
  - `_with_retries(self, fn: Callable[[], T]) -> T` — rules from https://dev.meta.ai/docs/error-handling:
    - **Retry**: `openai.RateLimitError` (429), `openai.APIStatusError` with status 500 or 503,
      `openai.APITimeoutError`, `openai.APIConnectionError`.
    - **Never retry**: 400, 401, 402, 403, 404, 413 and **504** → raise `MetaError` at once.
    - Max **4 attempts** in total (1 + 3 retries). After the last one → `MetaError`.
    - Wait before each retry: if the error response has a `Retry-After` header, wait that many
      seconds; else `min(60, 1 * 2**retry) + random.uniform(0, 1)`. Always call `self.sleep(...)`
      (never `time.sleep` directly) so tests are instant.
    - Log each error with `logging.getLogger(__name__).warning(...)`: status code and attempt
      number only. Never log the key or the request body.

Later tasks will add `upload_file`, `transcribe` and `segment` to this class. Not now.

## Docs
- Pricing: https://dev.meta.ai/docs/pricing-rate-limits
- Errors and retries: https://dev.meta.ai/docs/error-handling
- Client setup: https://dev.meta.ai/docs/sdks
- Usage fields: https://dev.meta.ai/docs/api-reference/responses/schemas
- Cached tokens: https://dev.meta.ai/docs/prompt-caching

## Done when
- `.venv/bin/pytest -q` passes and `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` are clean.
- `grep -rn "OpenAI(" app | grep -v meta_client.py` → no output.
- `tests/test_meta_client.py` has **at least** these tests, all with a fake client (no network):
  1. `token_cost("muse-spark-1.3", 1_000_000, 200_000, 100_000) == pytest.approx(1.455)`
  2. `sam_cost(images=10) == pytest.approx(0.025)` and `sam_cost(video_frames=1000) == pytest.approx(0.20)`
  3. `asr_cost(3600) == pytest.approx(0.18)` and `asr_cost(1.2) == asr_cost(2)`
  4. Normal `respond` call → returns the fake response and `spend.json` has `calls == 1` and the right total.
  5. A new `SpendCounter` on the same file reads the same total (it survives a restart).
  6. Spend already at budget → `BudgetExceeded`, and the fake client was **not** called.
  7. 429 with `Retry-After: 2` then success → `sleep` was called with `2.0`, result returned.
  8. 500 four times → `MetaError`, the fake client was called 4 times.
  9. 400 → `MetaError` after 1 call, no sleep. Same for 504.
  10. `APITimeoutError` then success → result returned.
  11. `max_output_tokens=1000` → `ValueError`. Unknown model → `ValueError`.
- `tests/test_config.py`: env values are read (use `monkeypatch.setenv`), defaults work without
  env, and `"secret-key" not in repr(get_settings())`.

## Notes
How to build fake errors and a fake client in tests:

```python
import httpx
import openai

REQ = httpx.Request("POST", "https://api.meta.ai/v1/responses")


def status_error(status: int, headers: dict | None = None) -> openai.APIStatusError:
    response = httpx.Response(status, headers=headers or {}, request=REQ)
    cls = openai.RateLimitError if status == 429 else openai.APIStatusError
    return cls(f"status {status}", response=response, body=None)


timeout_error = openai.APITimeoutError(request=REQ)


class FakeResponses:
    def __init__(self, results):  # list of responses or exceptions, used in order
        self.results = list(results)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, results):
        self.responses = FakeResponses(results)
```

A fake response can be `types.SimpleNamespace(usage=SimpleNamespace(input_tokens=..., input_tokens_details=SimpleNamespace(cached_tokens=...), output_tokens=...))`.
Use `tmp_path` for `data_dir` in every test, never the real `data/` folder.
