"""Client for the Meta Responses API with retries and a spend counter."""

import fcntl
import json
import logging
import math
import os
import random
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import httpx
import openai

from app.config import Settings

logger = logging.getLogger(__name__)

# Copied from https://dev.meta.ai/docs/pricing-rate-limits
PRICES: dict[str, dict[str, float]] = {
    "muse-spark-1.3": {
        "input_per_m": 1.25,
        "cached_input_per_m": 0.15,
        "output_per_m": 4.25,
    },
    "muse-wonder-1.0": {
        "input_per_m": 4.00,
        "cached_input_per_m": 0.20,
        "output_per_m": 20.00,
    },
    "sam-3.1": {
        "per_image": 0.0025,
        "per_video_frame": 0.0002,
    },
    "muse-voice-transcribe-1.0": {
        "per_hour": 0.18,
    },
    "muse-image-1.0": {
        "per_image": 0.01,
    },
}

T = TypeVar("T")

MAX_ATTEMPTS = 4
RETRYABLE_STATUSES = (429, 500, 503)
NON_RETRYABLE_STATUSES = (400, 401, 402, 403, 404, 413, 504)


class BudgetExceeded(Exception):
    """Raised before a call when spend is already at or over budget."""


class MetaError(Exception):
    """Non-retryable Meta API failure, or retries used up."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def token_cost(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    """Cost in USD. `cached_tokens` is a subset of `input_tokens`.

    See https://dev.meta.ai/docs/prompt-caching
    """
    if model not in PRICES or "input_per_m" not in PRICES[model]:
        raise ValueError(f"unknown model for token pricing: {model}")
    rates = PRICES[model]
    fresh = input_tokens - cached_tokens
    return (
        fresh * rates["input_per_m"]
        + cached_tokens * rates["cached_input_per_m"]
        + output_tokens * rates["output_per_m"]
    ) / 1_000_000


def sam_cost(images: int = 0, video_frames: int = 0) -> float:
    """Cost in USD for SAM masks ($2.50/1k images, $0.20/1k frames)."""
    rates = PRICES["sam-3.1"]
    return images * rates["per_image"] + video_frames * rates["per_video_frame"]


def asr_cost(seconds: float) -> float:
    """Cost in USD for transcription, metered in whole seconds."""
    billed = math.ceil(seconds)
    return billed / 3600 * PRICES["muse-voice-transcribe-1.0"]["per_hour"]


class SpendCounter:
    """Tracks spend in `data/spend.json` across restarts and processes."""

    def __init__(self, path: Path, budget_usd: float) -> None:
        self._path = path
        self._budget_usd = budget_usd

    def total(self) -> float:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return 0.0
        return float(data.get("total_usd", 0.0))

    def check(self) -> None:
        if self.total() >= self._budget_usd:
            raise BudgetExceeded(f"spend already at budget ${self._budget_usd:.2f}")

    def add(self, model: str, usd: float) -> float:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.parent / "spend.lock"
        lock_path.touch(exist_ok=True)
        with open(lock_path, "a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    with open(self._path, encoding="utf-8") as f:
                        data = json.load(f)
                except FileNotFoundError:
                    data = {}
                new_total = float(data.get("total_usd", 0.0)) + usd
                calls = int(data.get("calls", 0)) + 1
                by_model = dict(data.get("by_model", {}))
                by_model[model] = float(by_model.get(model, 0.0)) + usd
                payload = {
                    "total_usd": new_total,
                    "calls": calls,
                    "by_model": by_model,
                }
                with tempfile.NamedTemporaryFile(
                    dir=str(self._path.parent),
                    delete=False,
                    mode="w",
                    suffix=".tmp",
                    encoding="utf-8",
                ) as tmp:
                    json.dump(payload, tmp)
                    tmp_path = tmp.name
                os.replace(tmp_path, self._path)
                return new_total
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _retry_after_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        raw = headers.get("retry-after")
    except Exception:
        return None
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class MetaClient:
    """Thin wrapper over the OpenAI SDK pointed at the Meta API."""

    def __init__(
        self,
        settings: Settings,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if client is None:
            # Built exactly like https://dev.meta.ai/docs/sdks
            client = openai.OpenAI(
                api_key=settings.model_api_key,
                base_url=settings.meta_api_base,
                max_retries=0,
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
        self._client = client
        self._sleep = sleep
        self.spend = SpendCounter(settings.data_dir / "spend.json", settings.budget_usd)

    def respond(
        self,
        *,
        model: str,
        input: Any,
        max_output_tokens: int = 4000,
        **kwargs: Any,
    ) -> Any:
        if "input_per_m" not in PRICES.get(model, {}):
            raise ValueError(f"unknown model: {model}")
        if max_output_tokens < 4000:
            raise ValueError("max_output_tokens must be >= 4000")
        self.spend.check()
        response = self._with_retries(
            lambda: self._client.responses.create(
                model=model,
                input=input,
                max_output_tokens=max_output_tokens,
                **kwargs,
            )
        )
        usage = response.usage
        if usage is None:
            logger.warning("response without usage, spend not counted")
            return response
        details = getattr(usage, "input_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or 0
        cost = token_cost(model, usage.input_tokens, cached, usage.output_tokens)
        self.spend.add(model, cost)
        return response

    def upload_file(self, path: Path, expires_seconds: int = 86400) -> str:
        """Upload a video file for video understanding. Uploading is free."""
        if path.suffix != ".mp4":
            raise ValueError(f"only .mp4 videos can be uploaded: {path}")
        if path.stat().st_size > 1_073_741_824:
            raise ValueError(f"file is bigger than 1 GiB: {path}")

        def _do_upload() -> Any:
            with open(path, "rb") as f:
                return self._client.files.create(
                    purpose="user_data",
                    file=f,
                    expires_after={"anchor": "created_at", "seconds": expires_seconds},
                )

        return self._with_retries(_do_upload).id

    def delete_file(self, file_id: str) -> None:
        """Delete an uploaded file. Cleanup never raises."""
        try:
            self._with_retries(lambda: self._client.files.delete(file_id))
        except Exception:
            logger.warning("failed to delete file %s", file_id, exc_info=True)

    def _with_retries(self, fn: Callable[[], T]) -> T:
        last_exc: BaseException | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return fn()
            except openai.APIStatusError as exc:
                status = getattr(exc, "status_code", None)
                retryable = status in RETRYABLE_STATUSES or isinstance(exc, openai.RateLimitError)
                if not retryable:
                    logger.warning("meta api error status=%s attempt=%s", status, attempt)
                    raise MetaError(
                        f"meta api failed with status {status} on attempt {attempt}",
                        status_code=status,
                    ) from exc
                last_exc = exc
            except (openai.APITimeoutError, openai.APIConnectionError) as exc:
                last_exc = exc
                status = None
            if attempt >= MAX_ATTEMPTS:
                break
            wait = _retry_after_seconds(last_exc) if last_exc is not None else None
            if wait is None:
                wait = min(60.0, 1.0 * (2 ** (attempt - 1))) + random.uniform(0, 1)
            logger.warning("meta api error status=%s attempt=%s", status, attempt)
            self._sleep(wait)
        status = getattr(last_exc, "status_code", None)
        logger.warning("meta api error status=%s attempt=%s", status, MAX_ATTEMPTS)
        raise MetaError(
            f"meta api failed with status {status} after {MAX_ATTEMPTS} attempts",
            status_code=status,
        ) from last_exc
