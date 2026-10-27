"""One helper for strict-JSON Muse Spark calls, shared by the stages.

Analyze, identify and refine all do the same thing: send a prompt (plus
still images or an uploaded video) to Muse Spark, keep the raw answer and
parse it as strict JSON. This module holds that pattern once; each stage
keeps its own error class and maps failures to it.
"""

import base64
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app import artifacts
from app.config import Settings


class SparkAnswerError(Exception):
    """Spark's text is not valid JSON."""


def json_format(name: str, schema: dict) -> dict:
    """Strict JSON-schema response format for the Responses API."""
    return {"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}}


_MIME_BY_SUFFIX = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def image_block(path: Path) -> dict:
    """One image content block with the bytes as a data URL (mime from suffix)."""
    path = Path(path)
    mime = _MIME_BY_SUFFIX.get(path.suffix.lower())
    if mime is None:
        raise ValueError(f"unsupported image type: {path.suffix}")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "input_image", "image_url": f"data:{mime};base64,{data}"}


def ask_json(
    client: Any,
    settings: Settings,
    *,
    name: str,
    schema: dict,
    prompt: str,
    images: Sequence[Path] = (),
    video: Path | None = None,
    raw_path: Path | None = None,
    max_output_tokens: int = 4000,
    timeout_s: float | None = None,
    retry_timeouts: bool = True,
) -> Any:
    """Ask Spark for strict JSON and return the parsed answer.

    A video is uploaded first and always deleted afterwards, even when the
    call fails. The raw answer is saved to ``raw_path`` when given (also for
    answers that turn out not to be valid JSON). Anything that is not valid
    JSON raises SparkAnswerError; the caller maps it to its own error class.
    """
    content: list[dict] = [{"type": "input_text", "text": prompt}]
    for path in images:
        content.append(image_block(path))
    file_id: str | None = None
    if video is not None:
        file_id = client.upload_file(video)
    try:
        if file_id is not None:
            content.append({"type": "input_file", "file_id": file_id})
        response = client.respond(
            model=settings.spark_model,
            input=[{"role": "user", "content": content}],
            text=json_format(name, schema),
            max_output_tokens=max_output_tokens,
            timeout_s=timeout_s,
            retry_timeouts=retry_timeouts,
        )
    finally:
        if file_id is not None:
            client.delete_file(file_id)
    text = response.output_text or ""
    if raw_path is not None:
        artifacts.write_text_atomic(raw_path, text)
    try:
        return json.loads(text)
    except (ValueError, TypeError) as exc:
        raise SparkAnswerError(f"Spark returned invalid JSON for {name}") from exc
