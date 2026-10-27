"""Analyze stage: video plus spoken turns to repair steps via Muse Spark."""

import json
from pathlib import Path

from app import artifacts, spark
from app.config import Settings
from app.domains import DomainProfile, profile_for
from app.meta_client import MetaClient, make_client
from app.schemas import (
    ACTIONS,
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

TEXT_FORMAT = spark.json_format("repair_analysis", ANALYSIS_JSON_SCHEMA)

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
    task: str = "repair",
) -> str:
    """Fill the analyze prompt template with the job times, the turns and the task direction."""
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
    building = guide_direction(task) == "assemble"
    prompt = prompt.replace("<<GUIDE_KIND>>", "assembly" if building else "repair / disassembly")
    prompt = prompt.replace(
        "<<TASK_SENTENCE>>",
        "the person BUILDS or assembles the object: each step adds or fixes parts together."
        if building
        else f"the person does a {task}: each step takes apart, repairs or checks something.",
    )
    prompt = prompt.replace("<<FASTENER_VERB>>", "put in" if building else "taken out")
    prompt = prompt.replace("<<ACTIONS>>", ", ".join(ACTIONS))
    return prompt


def guide_direction(task: str | None) -> str:
    """'assemble' when the video builds something, else 'disassemble' (repairs take apart)."""
    return "assemble" if task == "assemble" else "disassemble"


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
    task = identity.task if identity else "repair"
    prompt = build_prompt(duration_s, mode, turns, segments, domain, task)
    if client is None:
        client = make_client(settings, job_dir=job_dir)
    try:
        data = spark.ask_json(
            client,
            settings,
            name="repair_analysis",
            schema=ANALYSIS_JSON_SCHEMA,
            prompt=prompt,
            video=video_path,
            raw_path=job_dir / "analysis_raw.txt",
            max_output_tokens=MAX_OUTPUT_TOKENS,
            timeout_s=ANALYZE_TIMEOUT_S,
            retry_timeouts=False,
        )
    except spark.SparkAnswerError as exc:
        raise AnalyzeError("Spark returned an invalid analysis") from exc
    # Keep Spark's raw answer: ask_json saved it to analysis_raw.txt, so a
    # parsing failure can still be debugged from the prompt.
    analysis = parse_analysis(json.dumps(data))
    artifacts.save(job_dir, analysis)
    return analysis
