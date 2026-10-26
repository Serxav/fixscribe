"""Transcription stage: WAV audio to timestamped turns."""

import json
import os
import tempfile
from pathlib import Path

from app.config import Settings
from app.meta_client import MetaClient


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
    turns = []
    for turn in data.get("turns", []):
        text = turn.get("transcript", "")
        if not text.strip():
            continue
        turns.append(
            {
                "start_s": turn["startMs"] / 1000,
                "end_s": turn["endMs"] / 1000,
                "text": text,
            }
        )
    turns.sort(key=lambda turn: turn["start_s"])
    total_words = sum(len(turn["text"].split()) for turn in turns)
    result = {
        "mode": "narrated" if total_words >= 5 else "silent",
        "duration_s": data["audioDurationMs"] / 1000,
        "transcript": data.get("transcript", ""),
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
