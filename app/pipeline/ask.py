"""Ask the coach out loud: next / back / repeat need no AI, anything else goes to Spark.

The phone sends one short spoken clip. Muse Voice Transcribe writes it down; a few fixed words move
the coach with no model at all, and a real question is answered from the guide and the camera.
Talk that is neither costs only the transcription and does nothing: people mutter while they work.
"""

import io
import re
import unicodedata
import wave
from pathlib import Path
from typing import Any, Literal

from app import artifacts, spark
from app.artifacts import ArtifactError
from app.config import Settings
from app.meta_client import BudgetExceeded, MetaError
from app.pipeline.live import (
    PROFESSIONAL_LINE,
    LiveError,
    _coach_client,
    _count_call,
    _describe_step,
    save_frame,
)
from app.schemas import Guide, Strict, _object
from app.spark import SparkAnswerError

MAX_CLIP_S = 8
MAX_CLIP_BYTES = 24000 * 2 * MAX_CLIP_S + 1024
MAX_COMMAND_WORDS = 4
LANGUAGES = ["Spanish", "English"]

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "ask_v1.md"

COMMANDS = {
    "next": ("next", "next step", "continue", "go on", "siguiente", "sigue", "continua"),
    "back": ("back", "go back", "previous", "atras", "anterior", "volver", "vuelve"),
    "repeat": ("repeat", "again", "say again", "repeat that", "repite", "repitelo", "otra vez"),
    "quiet": ("quiet", "be quiet", "stop talking", "silence", "silencio", "callate"),
}
KEYWORDS = sorted({phrase for phrases in COMMANDS.values() for phrase in phrases})
QUESTION_WORDS = frozenset(
    "what whats where wheres which how why when can should do does is are "
    "que donde cual cuales como cuanto cuantos cuantas por puedo debo hay es".split()
)
ANSWER_SCHEMA: dict[str, Any] = _object({"answer": {"type": "string"}})


class LiveHeard(Strict):
    """What the coach heard and what it does about it."""

    heard: str
    command: Literal["next", "back", "repeat", "quiet", "question", "none"]
    answer: str = ""


def _plain(text: str) -> str:
    """Lower case words with no accents or punctuation: "¡Repítelo!" is "repitelo"."""
    bare = unicodedata.normalize("NFKD", text.lower())
    bare = "".join(c for c in bare if not unicodedata.combining(c)).replace("'", "")
    return " ".join(re.findall(r"[a-z0-9]+", bare))


def parse_command(text: str) -> str:
    """The fixed command in a short sentence, "question" for a real question, else "none"."""
    words = _plain(text).split()
    if not words:
        return "none"
    if words[0] in QUESTION_WORDS and len(words) >= 2:  # "what's the next tool?" is no command
        return "question"
    if len(words) <= MAX_COMMAND_WORDS:
        padded = f" {' '.join(words)} "
        for command, phrases in COMMANDS.items():
            if any(f" {phrase} " in padded for phrase in phrases):
                return command
    return "none"


def check_clip(clip: bytes) -> None:
    """Refuse anything but a short mono 16-bit WAV at the rates Muse Voice accepts."""
    if not clip:
        raise LiveError("the voice clip is empty")
    if len(clip) > MAX_CLIP_BYTES:
        raise LiveError("the voice clip is too long")
    try:
        with wave.open(io.BytesIO(clip)) as wav:
            shape = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate())
            seconds = wav.getnframes() / max(1, wav.getframerate())
    except (wave.Error, EOFError) as exc:
        raise LiveError("the voice clip is not a WAV file") from exc
    if shape not in ((1, 2, 16000), (1, 2, 24000)) or seconds > MAX_CLIP_S:
        raise LiveError("the voice clip must be mono 16-bit 16 or 24 kHz and short")


def build_prompt(guide: Guide, step: int, question: str) -> str:
    """Fill the prompt with the guide, the warnings, the step and the question."""
    lines = [
        f"{_describe_step(s)} — warnings: {'; '.join(s.warnings) or 'none'}" for s in guide.steps
    ]
    language = (guide.language or "").strip() or "en"
    prompt = PROMPT_PATH.read_text(encoding="utf-8").replace("<<STEPS>>", "\n".join(lines))
    prompt = prompt.replace("<<STEP>>", str(step)).replace("<<LANGUAGE>>", language)
    return prompt.replace("<<QUESTION>>", question.replace('"', "'"))


def answer_question(
    job_dir: Path, settings: Settings, guide: Guide, step: int, question: str, frame: bytes, client
) -> str:
    """One short spoken answer from the guide and the camera."""
    calls = _count_call(job_dir)
    images = [save_frame(job_dir, frame, "question.jpg")] if frame else []
    try:
        data = spark.ask_json(
            client,
            settings,
            name="live_question",
            schema=ANSWER_SCHEMA,
            prompt=build_prompt(guide, step, question),
            images=images,
            max_output_tokens=12000,  # reasoning counts against this: a low cap leaves no answer
            timeout_s=30,
            effort="low",
        )
    except (SparkAnswerError, BudgetExceeded, MetaError) as exc:
        raise LiveError(f"could not answer the question: {exc}") from exc
    finally:
        artifacts.write_text_atomic(job_dir / "live" / "calls.txt", f"{calls + 1}\n")
    answer = data.get("answer") if isinstance(data, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        raise LiveError("could not answer the question: empty answer")
    return answer.strip()


def live_voice(
    job_dir: Path,
    settings: Settings,
    clip: bytes,
    step: int = 0,
    frame: bytes = b"",
    client: Any = None,
) -> LiveHeard:
    """One spoken clip in: what was heard, the command, and the answer when it was a question."""
    check_clip(clip)
    try:
        guide = artifacts.load(job_dir, Guide)
    except ArtifactError as exc:
        raise LiveError(f"no guide for this job: {exc}") from exc
    client = client or _coach_client(job_dir, settings)
    path = job_dir / "live" / "voice.wav"
    try:
        with artifacts.atomic_path(path) as tmp:
            Path(tmp).write_bytes(clip)
        data = client.transcribe(path, language_bias=LANGUAGES, keywords=KEYWORDS)
    except (BudgetExceeded, MetaError) as exc:
        raise LiveError(f"could not hear that: {exc}") from exc
    heard = data.get("transcript")
    heard = heard.strip() if isinstance(heard, str) else ""
    command = parse_command(heard)
    if command != "question":
        return LiveHeard(heard=heard, command=command)
    safety = guide.safety
    if safety is not None and safety.level == "professional_only":
        reason = safety.reasons[0] if safety.reasons else PROFESSIONAL_LINE
        return LiveHeard(heard=heard, command="question", answer=reason)
    answer = answer_question(job_dir, settings, guide, step, heard, frame, client)
    return LiveHeard(heard=heard, command="question", answer=answer)
