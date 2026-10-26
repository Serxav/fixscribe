"""Transcription stage: WAV audio to timestamped turns."""

import logging
from pathlib import Path

from app import artifacts
from app.config import Settings
from app.meta_client import MetaClient
from app.schemas import Transcript, Turn

logger = logging.getLogger(__name__)


def _is_number(value: object) -> bool:
    """True for a real JSON number (bools are not numbers here)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def run(job_dir: Path, settings: Settings, client: MetaClient | None = None) -> Transcript:
    """Transcribe the job audio, or mark the job silent when there is none."""
    wav = job_dir / "audio.wav"
    if not wav.exists():
        result = Transcript(mode="silent")
        artifacts.save(job_dir, result)
        return result
    if client is None:
        client = MetaClient(settings, job_dir=job_dir)
    data = client.transcribe(
        wav,
        mode="ENDPOINTING",
        language_bias=["Spanish", "English"],
        keywords=["step", "paso"],
    )
    raw_turns = data.get("turns")
    if not isinstance(raw_turns, list):
        raw_turns = []
    turns = []
    for index, turn in enumerate(raw_turns):
        if not isinstance(turn, dict):
            logger.warning("skipping turn %d: not an object", index)
            continue
        start_ms = turn.get("startMs")
        end_ms = turn.get("endMs")
        text = turn.get("transcript")
        if not _is_number(start_ms) or not _is_number(end_ms) or not isinstance(text, str):
            logger.warning("skipping turn %d: missing or invalid fields", index)
            continue
        if not text.strip():
            continue
        if start_ms < 0 or end_ms < start_ms:
            logger.warning("skipping turn %d: invalid times", index)
            continue
        turns.append(Turn(start_s=start_ms / 1000, end_s=end_ms / 1000, text=text))
    turns.sort(key=lambda turn: turn.start_s)
    total_words = sum(len(turn.text.split()) for turn in turns)
    raw_duration = data.get("audioDurationMs")
    duration_s = float(raw_duration) / 1000 if _is_number(raw_duration) else 0.0
    transcript_text = data.get("transcript", "")
    if not isinstance(transcript_text, str):
        transcript_text = ""
    result = Transcript(
        mode="narrated" if total_words >= 5 else "silent",
        duration_s=max(0.0, duration_s),
        transcript=transcript_text,
        turns=turns,
    )
    artifacts.save(job_dir, result)
    return result
