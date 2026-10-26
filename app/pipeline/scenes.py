"""Step-cut stage: spoken keywords to video segments."""

import json
import os
import re
import tempfile
from pathlib import Path

from app.config import Settings


class ScenesError(Exception):
    """Raised when the scene-cut inputs cannot be read."""


KEYWORD = re.compile(r"\b(step|paso)\b", re.IGNORECASE)


def keyword_cuts(turns: list[dict], min_gap_s: float = 3.0) -> list[float]:
    """Return the `start_s` of each turn that mentions the step keyword."""
    cuts: list[float] = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        text = turn.get("text", "")
        if not isinstance(text, str) or not KEYWORD.search(text):
            continue
        try:
            start_s = float(turn.get("start_s"))
        except (TypeError, ValueError):
            continue
        cuts.append(start_s)
    cuts.sort()
    kept: list[float] = []
    for cut in cuts:
        if kept and cut - kept[-1] < min_gap_s:
            continue
        kept.append(cut)
    return kept


def cuts_to_segments(cuts: list[float], duration_s: float, min_len_s: float = 2.0) -> list[dict]:
    """Turn cut points into segments covering the rest of the video."""
    ordered = sorted(cut for cut in cuts if cut < duration_s)
    if not ordered:
        return []
    segments = [
        {
            "start_s": round(float(cut), 2),
            "end_s": round(float(ordered[i + 1] if i + 1 < len(ordered) else duration_s), 2),
        }
        for i, cut in enumerate(ordered)
    ]
    merged: list[dict] = []
    for i, segment in enumerate(segments):
        if segment["end_s"] - segment["start_s"] < min_len_s:
            if merged:
                merged[-1]["end_s"] = segment["end_s"]
            elif i + 1 < len(segments):
                segments[i + 1]["start_s"] = segment["start_s"]
            else:
                merged.append(segment)
        else:
            merged.append(segment)
    return merged


def run(job_dir: Path, settings: Settings) -> dict:
    """Split the video into steps from the spoken keyword, or mark none."""
    del settings
    ingest = _read_json(job_dir / "ingest.json", "ingest.json")
    # No transcript (no audio, or transcription failed): treat the video as silent.
    transcript_path = job_dir / "transcript.json"
    transcript = (
        _read_json(transcript_path, "transcript.json")
        if transcript_path.exists()
        else {"mode": "silent", "turns": []}
    )
    if not isinstance(ingest, dict):
        raise ScenesError("broken ingest.json: expected a JSON object")
    if not isinstance(transcript, dict):
        raise ScenesError("broken transcript.json: expected a JSON object")
    try:
        duration_s = float(ingest["duration_s"])
    except (KeyError, TypeError, ValueError):
        raise ScenesError("broken ingest.json: missing or invalid 'duration_s'") from None
    if duration_s <= 0:
        raise ScenesError("broken ingest.json: 'duration_s' must be positive")
    turns = transcript.get("turns", [])
    if not isinstance(turns, list):
        raise ScenesError("broken transcript.json: missing or invalid 'turns'")

    cuts: list[float] = []
    segments: list[dict] = []
    if transcript.get("mode") == "narrated":
        cuts = [round(cut, 2) for cut in keyword_cuts(turns)]
        segments = cuts_to_segments(cuts, duration_s)

    source = "voice" if len(segments) >= 2 else "none"
    if source == "none":
        segments = []
    result = {"source": source, "cuts": cuts, "segments": segments}
    _write_json_atomic(job_dir / "scenes.json", result)
    return result


def _read_json(path: Path, name: str):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise ScenesError(f"missing {name}") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScenesError(f"broken {name}: {exc}") from None


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
