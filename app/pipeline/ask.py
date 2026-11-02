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
    scratch_folder,
)
from app.schemas import Guide, Strict, _object
from app.spark import SparkAnswerError

MAX_CLIP_S = 8
MAX_CLIP_BYTES = 24000 * 2 * MAX_CLIP_S + 1024
MAX_COMMAND_WORDS = 4
MAX_TYPED_CHARS = 200
LANGUAGES = ["Spanish", "English"]

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "ask_v2.md"

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
ANSWER_SCHEMA: dict[str, Any] = _object(
    {"answer": {"type": "string"}, "step": {"type": "integer"}}  # step 0: from no step
)


class LiveHeard(Strict):
    """What the coach heard and what it does about it."""

    heard: str
    command: Literal["next", "back", "repeat", "quiet", "question", "none"]
    answer: str = ""
    see_step: int = 0  # the step the answer comes from, 0 for none
    see_s: float | None = None  # where that step shows in the video: "see 01:42"


class Answer(Strict):
    """A spoken answer and the step it comes from."""

    text: str
    step: int = 0


def proof_second(guide: Guide, step: int) -> float | None:
    """Where the video shows a step: its sharpest frame, else its start; None for no such step."""
    for s in guide.steps:
        if s.index == step:
            return s.keyframe_s if s.keyframe_s is not None else s.start_s
    return None


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
) -> Answer:
    """One short spoken answer from the guide and the camera."""
    calls = _count_call(job_dir, settings)
    try:
        with scratch_folder(job_dir) as folder:
            images = [save_frame(folder, frame, "question.jpg")] if frame else []
            data = spark.ask_json(
                client,
                settings,
                name="live_question",
                schema=ANSWER_SCHEMA,
                prompt=build_prompt(guide, step, question),
                images=images,
                # reasoning counts against this: a low cap leaves no answer
                max_output_tokens=12000,
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
    source = data.get("step")
    known = isinstance(source, int) and proof_second(guide, source) is not None
    return Answer(text=answer.strip(), step=source if known else 0)


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
    try:
        with scratch_folder(job_dir) as folder:
            path = folder / "voice.wav"
            path.write_bytes(clip)
            data = client.transcribe(path, language_bias=LANGUAGES, keywords=KEYWORDS)
    except (BudgetExceeded, MetaError) as exc:
        raise LiveError(f"could not hear that: {exc}") from exc
    heard = data.get("transcript")
    heard = heard.strip() if isinstance(heard, str) else ""
    command = parse_command(heard)
    return obey_words(job_dir, settings, guide, heard, command, step, frame, client)


def obey_words(
    job_dir: Path,
    settings: Settings,
    guide: Guide,
    heard: str,
    command: str,
    step: int,
    frame: bytes,
    client: Any,
) -> LiveHeard:
    """A fixed command moves the coach; a question gets its answer from the guide and camera."""
    if command != "question":
        return LiveHeard(heard=heard, command=command)
    safety = guide.safety
    if safety is not None and safety.level == "professional_only":
        reason = safety.reasons[0] if safety.reasons else PROFESSIONAL_LINE
        return LiveHeard(heard=heard, command="question", answer=reason)
    answer = answer_question(job_dir, settings, guide, step, heard, frame, client)
    return LiveHeard(
        heard=heard,
        command="question",
        answer=answer.text,
        see_step=answer.step,
        see_s=proof_second(guide, answer.step),
    )


def live_typed(
    job_dir: Path,
    settings: Settings,
    text: str,
    step: int = 0,
    frame: bytes = b"",
    client: Any = None,
) -> LiveHeard:
    """A typed line: the same as speaking it, with no transcription. Any typed line is a question
    unless it is a short command, since nobody types by accident."""
    text = " ".join(text.split())[:MAX_TYPED_CHARS]
    if not text:
        raise LiveError("the question is empty")
    try:
        guide = artifacts.load(job_dir, Guide)
    except ArtifactError as exc:
        raise LiveError(f"no guide for this job: {exc}") from exc
    command = parse_command(text)
    if command == "none":
        command = "question" if len(_plain(text).split()) >= 2 else "none"
    if command == "question":
        client = client or _coach_client(job_dir, settings)
    return obey_words(job_dir, settings, guide, text, command, step, frame, client)
