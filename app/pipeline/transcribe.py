"""Transcription stage: WAV audio to timestamped turns."""

import json
import logging
import os
import tempfile
from pathlib import Path

from app.config import Settings
from app.meta_client import MetaClient

logger = logging.getLogger(__name__)


def _is_number(value: object) -> bool:
    """True for a real JSON number (bools are not numbers here)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def run(job_dir: Path, settings: Settings, client: MetaClient | None = None) -> dict:
    """Transcribe the job audio, or mark the job silent when there is none."""
    transcript_path = job_dir / "transcript.json"
    wav = job_dir / "audio.wav"
    if not wav.exists():
        result: dict = {
            "mode": "silent",
            "duration_s": 0.0,
            "transcript": "",
            "turns": [],
        }
        _write_json_atomic(transcript_path, result)
        return result
    if client is None:
        client = MetaClient(settings)
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
        turns.append(
            {
                "start_s": start_ms / 1000,
                "end_s": end_ms / 1000,
                "text": text,
            }
        )
    turns.sort(key=lambda turn: turn["start_s"])
    total_words = sum(len(turn["text"].split()) for turn in turns)
    raw_duration = data.get("audioDurationMs")
    duration_s = float(raw_duration) / 1000 if _is_number(raw_duration) else 0.0
    transcript_text = data.get("transcript", "")
    if not isinstance(transcript_text, str):
        transcript_text = ""
    result = {
        "mode": "narrated" if total_words >= 5 else "silent",
        "duration_s": duration_s,
        "transcript": transcript_text,
        "turns": turns,
    }
    _write_json_atomic(transcript_path, result)
    return result


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
