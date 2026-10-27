"""Analyze stage: video plus spoken turns to repair steps via Muse Spark."""

import json
from pathlib import Path

from app import artifacts
from app.config import Settings
from app.domains import DomainProfile, profile_for
from app.meta_client import MetaClient
from app.schemas import (
    ANALYSIS_JSON_SCHEMA,
    Analysis,
    Identity,
    IngestInfo,
    Scenes,
    Transcript,
)


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
ANALYZE_TIMEOUT_S = 600.0


def domain_context(identity: Identity | None, profile: DomainProfile) -> str:
    """Short domain block for the prompt, steered by what identify found."""
    tail = [
        profile.prompt_hint,
        f"Typical parts: {', '.join(profile.parts)}",
        f"Fasteners in this domain: {', '.join(profile.fasteners)}; count them as `screw_count`.",
    ]
    if identity is None:
        return "\n".join(tail)
    problem = identity.problem or "not stated"
    brand_model = f"{identity.brand} {identity.model}".strip() or "unknown"
    head = [
        f"Object: {identity.object_name} ({identity.category}), "
        f"task: {identity.task}, problem: {problem}",
        f"Brand/model: {brand_model}",
    ]
    return "\n".join(head + tail)


def build_prompt(
    duration_s: float,
    mode: str,
    turns: list[dict],
    segments: list[dict],
    domain: str = "",
) -> str:
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
    prompt = prompt.replace("<<DOMAIN>>", domain)
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
    if not video_path.is_file():
        raise AnalyzeError("missing video.mp4")
    ingest = artifacts.load(job_dir, IngestInfo)
    transcript = artifacts.load_optional(job_dir, Transcript)
    scenes = artifacts.load_optional(job_dir, Scenes)
    mode = transcript.mode if transcript else "silent"
    turns = [turn.model_dump() for turn in transcript.turns] if transcript else []
    segments = (
        [segment.model_dump() for segment in scenes.segments]
        if scenes and scenes.source == "voice"
        else []
    )
    duration_s = ingest.duration_s

    identity = artifacts.load_optional(job_dir, Identity)
    profile = profile_for(identity.category if identity else None)
    domain = domain_context(identity, profile)
    prompt = build_prompt(duration_s, mode, turns, segments, domain)
    if client is None:
        client = MetaClient(settings, job_dir=job_dir)
    file_id = client.upload_file(video_path)
    try:
        response = client.respond(
            model=settings.spark_model,
            input=build_input(prompt, file_id),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            text=TEXT_FORMAT,
            timeout_s=ANALYZE_TIMEOUT_S,
            retry_timeouts=False,
        )
    finally:
        client.delete_file(file_id)
    # Keep Spark's raw answer: if parsing fails, this is what we need to debug the prompt.
    (job_dir / "analysis_raw.txt").write_text(response.output_text or "", encoding="utf-8")
    analysis = parse_analysis(response.output_text)
    artifacts.save(job_dir, analysis)
    return analysis
