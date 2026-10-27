"""Identify stage: look at a few frames (plus the first spoken words) via Muse Spark.

The answer (identity.json) tells every later stage what the object is, its category,
the task, the visible hazards, the skill level, the language and the evidence.
"""

import base64
import json
import shutil
from pathlib import Path

from app import artifacts
from app.config import Settings
from app.meta_client import MetaClient, make_client
from app.pipeline import media
from app.pipeline.ingest import find_original
from app.schemas import IDENTITY_JSON_SCHEMA, Identity, IngestInfo, Transcript

VERSION = "1"
N_FRAMES = 4
MAX_SIDE = 768
MAX_OUTPUT_TOKENS = 4000
IDENTIFY_TIMEOUT_S = 120.0
MAX_TRANSCRIPT_CHARS = 1500

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "identify_v1.md"


class IdentifyError(Exception):
    """Raised when the identify inputs or the Spark answer are unusable."""


def frame_times(duration_s: float, n: int = N_FRAMES) -> list[float]:
    """Spread n sample times inside the video, away from the very start and end."""
    if duration_s <= 0:
        raise ValueError("duration must be positive")
    if n <= 0:
        raise ValueError("n must be positive")
    if n == 1:
        return [duration_s * 0.5]
    return [duration_s * (0.1 + 0.8 * i / (n - 1)) for i in range(n)]


def spoken_text(transcript: Transcript | None) -> str:
    """The words spoken, from the full transcript or, if it is empty, from the turns."""
    if transcript is None:
        return ""
    return transcript.transcript or " ".join(turn.text for turn in transcript.turns)


def build_prompt(transcript_text: str) -> str:
    """Fill the identify prompt template with the first spoken words."""
    template = PROMPT_PATH.read_text(encoding="utf-8")
    snippet = transcript_text[:MAX_TRANSCRIPT_CHARS] if transcript_text else "(no speech)"
    return template.replace("<<TRANSCRIPT>>", snippet)


def image_data_url(path: Path) -> str:
    """Encode a PNG still as a data URL for the Responses API."""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def build_input(prompt: str, images: list[Path]) -> list[dict]:
    """Multimodal input: a text prompt followed by one image block per still."""
    content: list[dict] = [{"type": "input_text", "text": prompt}]
    for path in images:
        content.append({"type": "input_image", "image_url": image_data_url(path)})
    return [{"role": "user", "content": content}]


def parse_identity(text: str) -> Identity:
    """Parse the Spark answer into an Identity or raise IdentifyError."""
    try:
        return Identity.model_validate(json.loads(text))
    except Exception as exc:
        raise IdentifyError("Spark returned an invalid identity") from exc


def run(job_dir: Path, settings: Settings, client: MetaClient | None = None) -> Identity:
    """Look at N_FRAMES stills and save what the video shows as identity.json."""
    ingest = artifacts.load(job_dir, IngestInfo)
    transcript = artifacts.load_optional(job_dir, Transcript)
    if client is None:
        client = make_client(settings, job_dir=job_dir)
    stills_dir = job_dir / "identify"
    try:
        if ingest.source is None:
            raise IdentifyError("ingest has no source info")
        original = find_original(job_dir)
        paths = media.extract_stills(
            original,
            ingest.source,
            frame_times(ingest.duration_s),
            stills_dir,
            max_side=MAX_SIDE,
        )
        transcript_text = spoken_text(transcript)
        prompt = build_prompt(transcript_text)
        response = client.respond(
            model=settings.spark_model,
            input=build_input(prompt, paths),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "repair_identity",
                    "schema": IDENTITY_JSON_SCHEMA,
                    "strict": True,
                }
            },
            timeout_s=IDENTIFY_TIMEOUT_S,
        )
        # Keep Spark's raw answer: if parsing fails, this is what we debug the prompt with.
        raw = response.output_text or ""
        (job_dir / "identify_raw.txt").write_text(raw, encoding="utf-8")
        identity = parse_identity(raw)
        artifacts.save(job_dir, identity)
        return identity
    finally:
        shutil.rmtree(stills_dir, ignore_errors=True)
