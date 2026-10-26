"""One real Muse Spark call on a repair video, scored against hand-written times.

Usage: .venv/bin/python scripts/first_call.py samples/<name>.mp4

Sergi runs this once with a real video; tests never touch the network.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from app.config import get_settings
from app.meta_client import BudgetExceeded, MetaClient, MetaError

PROMPT = (
    "Watch this repair video and list the repair steps as JSON only, with no other text. "
    'Reply with exactly this shape: {"steps": [{"title": str, "start_s": float, '
    '"end_s": float}]}. Times are seconds from the start of the video. '
    "Start a new step every time the technician starts a new action "
    'or says the word "step" or "paso". '
    "Write the titles in English, one entry per step, in video order."
)

DEFAULT_TOLERANCE_S = 2.0
MAX_OUTPUT_TOKENS = 8000


def video_seconds(path: Path) -> float:
    """Length of a video in seconds, read with ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return float(result.stdout.strip())


def build_input(file_id: str) -> list[dict]:
    """Video-understanding input: a text prompt plus the uploaded file."""
    return [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": PROMPT},
                {"type": "input_file", "file_id": file_id},
            ],
        }
    ]


def parse_steps(text: str) -> list[dict]:
    """Parse the model steps JSON, plain or inside a ```json fence."""
    candidate = text.strip()
    if "```" in candidate:
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", candidate, re.DOTALL)
        if match is None:
            raise ValueError("model did not return valid steps JSON")
        candidate = match.group(1).strip()
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        raise ValueError("model did not return valid steps JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        raise ValueError("model did not return valid steps JSON")
    steps = data["steps"]
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("model did not return valid steps JSON")
        title = step.get("title")
        start = step.get("start_s")
        end = step.get("end_s")
        if not isinstance(title, str):
            raise ValueError("model did not return valid steps JSON")
        if (
            isinstance(start, bool)
            or not isinstance(start, (int, float))
            or isinstance(end, bool)
            or not isinstance(end, (int, float))
        ):
            raise ValueError("model did not return valid steps JSON")
        if not 0 <= start < end:
            raise ValueError("model did not return valid steps JSON")
    return steps


def compare_steps(
    found: list[dict], expected: list[dict], tolerance_s: float = DEFAULT_TOLERANCE_S
) -> dict:
    """Score found steps against expected ones, matched by position."""
    rows = []
    hits = 0
    for i in range(max(len(found), len(expected))):
        if i < len(found) and i < len(expected):
            start_error = abs(found[i]["start_s"] - expected[i]["start_s"])
            end_error = abs(found[i]["end_s"] - expected[i]["end_s"])
            hit = start_error <= tolerance_s and end_error <= tolerance_s
            if hit:
                hits += 1
            rows.append(
                {
                    "index": i + 1,
                    "title": found[i].get("title", ""),
                    "start_error_s": start_error,
                    "end_error_s": end_error,
                    "hit": hit,
                }
            )
        elif i < len(found):
            rows.append(
                {
                    "index": i + 1,
                    "title": found[i].get("title", ""),
                    "start_error_s": None,
                    "end_error_s": None,
                    "hit": False,
                }
            )
        else:
            rows.append(
                {
                    "index": i + 1,
                    "title": expected[i].get("title", ""),
                    "start_error_s": None,
                    "end_error_s": None,
                    "hit": False,
                }
            )
    return {
        "expected": len(expected),
        "found": len(found),
        "hits": hits,
        "rows": rows,
    }


def _format_error(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "-"


def main(argv: list[str] | None = None) -> int:
    """Run one scored Spark call. Returns a process exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Usage: .venv/bin/python scripts/first_call.py samples/<name>.mp4")
        return 2
    video_path = Path(args[0])
    expected_path = video_path.with_suffix(".expected.json")
    if not video_path.exists():
        print(f"Video not found: {video_path}")
        return 1
    if not expected_path.exists():
        print(f"Expected times not found: {expected_path}")
        return 1
    settings = get_settings()
    if not settings.model_api_key:
        print("MODEL_API_KEY is not set")
        return 1
    try:
        duration = video_seconds(video_path)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Could not read video duration: {exc}")
        return 1
    if duration > settings.max_video_seconds:
        print(f"Video is {duration:.1f}s, over the {settings.max_video_seconds}s limit")
        return 1
    try:
        expected_steps = json.loads(expected_path.read_text(encoding="utf-8"))["steps"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Could not read expected times: {exc}")
        return 1
    if not isinstance(expected_steps, list):
        print(f"Could not read expected times: {expected_path}")
        return 1
    client = MetaClient(settings)
    spend_before = client.spend.total()
    print(f"Spend before: ${spend_before:.4f}")
    try:
        file_id = client.upload_file(video_path)
    except (BudgetExceeded, MetaError, ValueError, OSError) as exc:
        print(f"Upload failed: {exc}")
        return 1
    try:
        response = client.respond(
            model=settings.spark_model,
            input=build_input(file_id),
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
    except (BudgetExceeded, MetaError) as exc:
        print(f"Error: {exc}")
        return 1
    finally:
        client.delete_file(file_id)
    text = response.output_text
    try:
        found_steps = parse_steps(text)
    except ValueError:
        print("model did not return valid steps JSON")
        found_steps = []
    comparison = compare_steps(found_steps, expected_steps)
    out_path = settings.data_dir / "first_call" / f"{video_path.stem}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        dir=out_path.parent,
        prefix=f".{out_path.name}.",
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        json.dump(
            {"video": str(video_path), "output_text": text, "comparison": comparison},
            tmp,
            indent=2,
        )
        tmp_path = tmp.name
    os.replace(tmp_path, out_path)
    print("step  title  start_err_s  end_err_s  hit")
    for row in comparison["rows"]:
        mark = "HIT" if row["hit"] else "MISS"
        print(
            f"{row['index']:>4}  {row['title']}  "
            f"{_format_error(row['start_error_s'])}  "
            f"{_format_error(row['end_error_s'])}  {mark}"
        )
    print(
        f"Steps within ±{DEFAULT_TOLERANCE_S:.1f} s: {comparison['hits']}/{comparison['expected']}"
    )
    spend_after = client.spend.total()
    print(f"This call: ${spend_after - spend_before:.4f}")
    print(f"Spend after: ${spend_after:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
