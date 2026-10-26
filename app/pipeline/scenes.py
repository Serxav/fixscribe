"""Step-cut stage: spoken keywords to video segments."""

import re
from pathlib import Path

from app import artifacts
from app.artifacts import ArtifactError
from app.config import Settings
from app.schemas import IngestInfo, Scenes, Segment, Transcript, Turn


class ScenesError(Exception):
    """Raised when the scene-cut inputs cannot be read."""


KEYWORD = re.compile(r"\b(step|paso)\b", re.IGNORECASE)


def _turn_fields(turn: object) -> tuple[float, float, str] | None:
    if isinstance(turn, Turn):
        return float(turn.start_s), float(turn.end_s), turn.text
    if isinstance(turn, dict):
        text = turn.get("text", "")
        if not isinstance(text, str):
            return None
        try:
            start_s = float(turn.get("start_s"))  # type: ignore[arg-type]
            end_s = float(turn.get("end_s"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return start_s, end_s, text
    return None


def _kept_keyword_turns(turns: list, min_gap_s: float = 3.0) -> list[tuple[float, float]]:
    """Return ``(start_s, end_s)`` of keyword turns, dropping cuts closer than ``min_gap_s``."""
    matched: list[tuple[float, float]] = []
    for turn in turns:
        fields = _turn_fields(turn)
        if fields is None:
            continue
        start_s, end_s, text = fields
        if not KEYWORD.search(text):
            continue
        matched.append((start_s, end_s))
    matched.sort(key=lambda pair: pair[0])
    kept: list[tuple[float, float]] = []
    for start_s, end_s in matched:
        if kept and start_s - kept[-1][0] < min_gap_s:
            continue
        kept.append((start_s, end_s))
    return kept


def keyword_cuts(turns: list[dict], min_gap_s: float = 3.0) -> list[float]:
    """Return the `start_s` of each turn that mentions the step keyword."""
    return [start for start, _end in _kept_keyword_turns(list(turns), min_gap_s)]


def cuts_to_segments(cuts: list[float], duration_s: float, min_len_s: float = 2.0) -> list[dict]:
    """Turn cut points into segments covering the video.

    One segment per cut, plus a first segment ``[0, first_cut]`` when the first
    cut is at least 3 s after 0. Short segments are merged as before.
    """
    ordered = sorted(cut for cut in cuts if cut < duration_s)
    if not ordered:
        return []
    starts: list[float] = list(ordered)
    if ordered[0] >= 3.0:
        starts = [0.0, *ordered]
    raw: list[dict] = [
        {
            "start_s": round(float(start), 2),
            "end_s": round(float(starts[i + 1] if i + 1 < len(starts) else duration_s), 2),
        }
        for i, start in enumerate(starts)
    ]
    merged: list[dict] = []
    for i, segment in enumerate(raw):
        if segment["end_s"] - segment["start_s"] < min_len_s:
            if merged:
                merged[-1]["end_s"] = segment["end_s"]
            elif i + 1 < len(raw):
                raw[i + 1]["start_s"] = segment["start_s"]
            else:
                merged.append(segment)
        else:
            merged.append(segment)
    return merged


def run(job_dir: Path, settings: Settings) -> Scenes:
    """Split the video into steps from the spoken keyword, or mark none."""
    del settings
    try:
        ingest = artifacts.load(job_dir, IngestInfo)
    except ArtifactError as exc:
        raise ScenesError(str(exc)) from None
    try:
        transcript = artifacts.load_optional(job_dir, Transcript)
    except ArtifactError as exc:
        raise ScenesError(str(exc)) from None
    if transcript is None:
        transcript = Transcript(mode="silent", turns=[])
    duration_s = float(ingest.duration_s)
    if duration_s <= 0:
        raise ScenesError("broken ingest.json: 'duration_s' must be positive")

    cuts: list[float] = []
    cut_intervals: list[Segment] = []
    segments: list[Segment] = []
    if transcript.mode == "narrated":
        kept = _kept_keyword_turns(list(transcript.turns))
        cuts = [round(float(start), 2) for start, _end in kept]
        cut_intervals = [
            Segment(start_s=round(float(start), 2), end_s=round(float(end), 2))
            for start, end in kept
        ]
        segment_dicts = cuts_to_segments(cuts, duration_s)
        segments = [
            Segment(start_s=float(s["start_s"]), end_s=float(s["end_s"])) for s in segment_dicts
        ]

    source = "voice" if cuts else "none"
    if source == "none":
        segments = []
        cuts = cuts if transcript.mode == "narrated" else []
        if source == "none" and not cuts:
            cut_intervals = []
    result = Scenes(source=source, cuts=cuts, cut_intervals=cut_intervals, segments=segments)
    artifacts.save(job_dir, result)
    return result
