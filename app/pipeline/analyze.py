"""Analyze stage: video plus spoken turns to repair steps via Muse Spark."""

import json
import os
import tempfile
from pathlib import Path

from app.config import Settings
from app.meta_client import MetaClient
from app.schemas import ANALYSIS_JSON_SCHEMA, Analysis


class AnalyzeError(Exception):
    """Raised when the analyze inputs or the Spark answer are unusable."""


PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "analyze_v1.md"

TEXT_FORMAT = {
    "format": {
        "type": "json_schema",
        "name": "repair_analysis",
        "schema": ANALYSIS_JSON_SCHEMA,
        "strict": True,
    }
}

MAX_OUTPUT_TOKENS = 16000


def build_prompt(duration_s: float, mode: str, turns: list[dict], segments: list[dict]) -> str:
    """Fill the analyze prompt template with the job times and turns."""
    if turns:
        turn_lines = [
            f"- [{float(turn['start_s']):.1f}–{float(turn['end_s']):.1f} s] {turn['text']}"
            for turn in turns
        ]
        turns_text = "\n".join(turn_lines)
    else:
        turns_text = "- (none)"
    if segments:
        segment_lines = [
            f"- step {i}: {float(segment['start_s']):.1f}–{float(segment['end_s']):.1f} s"
            for i, segment in enumerate(segments, start=1)
        ]
        segments_text = "\n".join(segment_lines)
    else:
        segments_text = "- (none)"
    template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.replace("<<DURATION_S>>", f"{duration_s:.1f}")
    prompt = prompt.replace("<<MODE>>", mode)
    prompt = prompt.replace("<<TURNS>>", turns_text)
    prompt = prompt.replace("<<SEGMENTS>>", segments_text)
    return prompt


def build_input(prompt: str, file_id: str) -> list[dict]:
    """Video-understanding input: a text prompt plus the uploaded file."""
    return [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_file", "file_id": file_id},
            ],
        }
    ]


def parse_analysis(text: str) -> Analysis:
    """Parse the Spark answer into an Analysis or raise AnalyzeError."""
    try:
        return Analysis.model_validate(json.loads(text))
    except Exception as exc:
        raise AnalyzeError("Spark returned an invalid analysis") from exc


def run(job_dir: Path, settings: Settings, client: MetaClient | None = None) -> Analysis:
    """Send the job video to Spark and save its answer as analysis.json."""
    video_path = job_dir / "video.mp4"
    ingest_path = job_dir / "ingest.json"
    if not video_path.is_file():
        raise AnalyzeError("missing video.mp4")
    if not ingest_path.is_file():
        raise AnalyzeError("missing ingest.json")
    ingest = _read_json(ingest_path, "ingest.json")
    try:
        duration_s = float(ingest["duration_s"])
    except (KeyError, TypeError, ValueError):
        raise AnalyzeError("broken ingest.json: missing or invalid 'duration_s'") from None

    transcript_path = job_dir / "transcript.json"
    if transcript_path.exists():
        transcript = _read_json(transcript_path, "transcript.json")
        if not isinstance(transcript, dict):
            raise AnalyzeError("broken transcript.json: expected a JSON object")
        mode = transcript.get("mode", "silent")
        turns = transcript.get("turns", [])
        if not isinstance(turns, list):
            raise AnalyzeError("broken transcript.json: missing or invalid 'turns'")
    else:
        mode = "silent"
        turns = []

    scenes_path = job_dir / "scenes.json"
    segments: list[dict] = []
    if scenes_path.exists():
        scenes = _read_json(scenes_path, "scenes.json")
        if not isinstance(scenes, dict):
            raise AnalyzeError("broken scenes.json: expected a JSON object")
        if scenes.get("source") == "voice":
            segments = scenes.get("segments", [])
            if not isinstance(segments, list):
                raise AnalyzeError("broken scenes.json: missing or invalid 'segments'")

    prompt = build_prompt(duration_s, mode, turns, segments)
    if client is None:
        client = MetaClient(settings)
    file_id = client.upload_file(video_path)
    try:
        response = client.respond(
            model=settings.spark_model,
            input=build_input(prompt, file_id),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            text=TEXT_FORMAT,
        )
    finally:
        client.delete_file(file_id)
    analysis = parse_analysis(response.output_text)
    _write_json_atomic(job_dir / "analysis.json", analysis.model_dump(mode="json"))
    return analysis


def _read_json(path: Path, name: str):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise AnalyzeError(f"missing {name}") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnalyzeError(f"broken {name}: {exc}") from None


def _write_json_atomic(path: Path, payload: dict) -> None:
    with tempfile.NamedTemporaryFile(
        dir=str(path.parent),
        delete=False,
        mode="w",
        suffix=".tmp",
        encoding="utf-8",
    ) as tmp:
        json.dump(payload, tmp)
        tmp_path = tmp.name
    os.replace(tmp_path, path)
