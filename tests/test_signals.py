"""Tests for the visual-signals stage."""

import json
import shutil
import subprocess
import time

import pytest

from app.config import Settings
from app.pipeline import signals
from app.pipeline.signals import (
    SignalsError,
    find_pauses,
    find_scene_changes,
    rank_candidates,
    smooth,
)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def _run_ffmpeg(args, timeout=120):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True, timeout=timeout)


def _make_pause_video(path):
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x568:rate=30:duration=3",
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:size=320x568:rate=30:duration=2",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x568:rate=30:duration=3",
            "-filter_complex",
            "[0:v][1:v][2:v]concat=n=3:v=1:a=0[out]",
            "-map",
            "[out]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )


def _make_scene_video(path):
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=red:size=320x568:rate=30:duration=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:size=320x568:rate=30:duration=2",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[out]",
            "-map",
            "[out]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )


def _make_testsrc_video(path, duration=60):
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=320x568:rate=30:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        timeout=180,
    )


def test_smooth_centered_moving_average():
    assert smooth([0.0, 0.0, 3.0, 0.0, 0.0]) == [0.0, 1.0, 1.0, 1.0, 0.0]
    assert smooth([1.0, 2.0, 3.0], window=1) == [1.0, 2.0, 3.0]
    assert smooth([], window=3) == []
    assert len(smooth([1.0] * 10)) == 10


def test_smooth_keeps_constant_values():
    assert smooth([2.0, 2.0, 2.0, 2.0]) == [2.0, 2.0, 2.0, 2.0]


def test_find_pauses_hand_made_curve():
    motion = []
    values = [0.5] * 8 + [0.0] * 8 + [0.5] * 8
    for i, value in enumerate(values):
        motion.append([i * 0.25, value])
    pauses = find_pauses(motion)
    assert len(pauses) == 1
    assert pauses[0]["kind"] == "pause"
    assert 1.5 <= pauses[0]["t"] <= 3.5
    assert 0.0 <= pauses[0]["score"] <= 1.0


def test_find_pauses_ignores_short_dip_and_empty():
    assert find_pauses([]) == []
    motion = [[i * 0.25, 0.5] for i in range(12)]
    motion[5] = [1.25, 0.0]
    assert find_pauses(motion) == []


def test_find_pauses_all_still_is_one_pause():
    motion = [[i * 0.25, 0.0] for i in range(16)]
    pauses = find_pauses(motion)
    # Threshold is at least 0.002, so a fully still curve stays below it.
    assert len(pauses) == 1
    assert pauses[0]["score"] == 1.0


def test_find_scene_changes_hand_made_curve():
    scene = [[i * 0.5, 0.0] for i in range(21)]
    scene[10] = [5.0, 0.95]
    changes = find_scene_changes(scene)
    assert changes == [{"t": 5.0, "kind": "scene", "score": 0.95}]


def test_find_scene_changes_requires_peak_above_threshold():
    assert find_scene_changes([]) == []
    assert find_scene_changes([[0.0, 0.0], [1.0, 0.9]]) == []
    flat = [[float(i), 0.1] for i in range(10)]
    assert find_scene_changes(flat) == []
    not_peak = [[i * 0.5, 0.0] for i in range(21)]
    not_peak[10] = [5.0, 0.9]
    not_peak[11] = [5.5, 0.95]
    not_peak[12] = [6.0, 0.9]
    # The middle sample is the only strict peak; edges of a plateau are not.
    result = find_scene_changes(not_peak)
    assert all(candidate["t"] != 5.0 for candidate in result)


def test_find_scene_changes_caps_score_at_one():
    scene = [[i * 0.5, 0.0] for i in range(21)]
    scene[10] = [5.0, 1.4]
    changes = find_scene_changes(scene)
    assert changes[0]["score"] == 1.0


def test_rank_candidates_drops_edges():
    candidates = [
        {"t": 0.5, "kind": "pause", "score": 0.9},
        {"t": 5.0, "kind": "pause", "score": 0.5},
        {"t": 9.5, "kind": "scene", "score": 0.9},
    ]
    assert rank_candidates(candidates, 10.0) == [{"t": 5.0, "kind": "pause", "score": 0.5}]


def test_rank_candidates_keeps_edges_at_exactly_edge_s():
    candidates = [
        {"t": 1.0, "kind": "pause", "score": 0.5},
        {"t": 9.0, "kind": "scene", "score": 0.5},
    ]
    assert len(rank_candidates(candidates, 10.0)) == 2


def test_rank_candidates_min_gap_keeps_higher_score():
    candidates = [
        {"t": 3.0, "kind": "pause", "score": 0.4},
        {"t": 4.0, "kind": "scene", "score": 0.9},
        {"t": 8.0, "kind": "pause", "score": 0.7},
    ]
    result = rank_candidates(candidates, 12.0)
    assert result == [
        {"t": 4.0, "kind": "scene", "score": 0.9},
        {"t": 8.0, "kind": "pause", "score": 0.7},
    ]


def test_rank_candidates_returns_sorted_by_time():
    candidates = [
        {"t": 8.0, "kind": "pause", "score": 0.7},
        {"t": 3.0, "kind": "pause", "score": 0.4},
    ]
    result = rank_candidates(candidates, 12.0)
    assert [candidate["t"] for candidate in result] == [3.0, 8.0]
    assert rank_candidates([], 10.0) == []


@needs_ffmpeg
def test_pause_candidate_in_synthetic_video(tmp_path):
    video = tmp_path / "video.mp4"
    _make_pause_video(video)
    result = signals.compute_signals(video)
    pauses = [c for c in _candidates(result) if c["kind"] == "pause"]
    assert len(pauses) == 1
    assert 3.0 <= pauses[0]["t"] <= 5.0


@needs_ffmpeg
def test_scene_candidate_in_synthetic_video(tmp_path):
    video = tmp_path / "video.mp4"
    _make_scene_video(video)
    result = signals.compute_signals(video)
    scenes = [c for c in _candidates(result) if c["kind"] == "scene"]
    assert len(scenes) == 1
    assert 1.5 <= scenes[0]["t"] <= 2.5


@needs_ffmpeg
def test_run_writes_signals_json(tmp_path):
    _make_scene_video(tmp_path / "video.mp4")
    settings = Settings(model_api_key="", data_dir=tmp_path)
    result = signals.run(tmp_path, settings)
    assert set(result.keys()) == {"fps", "duration_s", "motion", "scene", "candidates"}
    assert result["fps"] == 4
    assert result["duration_s"] == pytest.approx(4.0, abs=0.5)
    assert result["motion"][0][1] == 0.0
    assert result["scene"][0][1] == 0.0
    stored = json.loads((tmp_path / "signals.json").read_text(encoding="utf-8"))
    assert stored == result


def test_run_missing_video_raises(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    with pytest.raises(SignalsError, match="missing video.mp4"):
        signals.run(tmp_path, settings)


@needs_ffmpeg
def test_run_unreadable_video_raises(tmp_path):
    (tmp_path / "video.mp4").write_bytes(b"not a video")
    settings = Settings(model_api_key="", data_dir=tmp_path)
    with pytest.raises(SignalsError, match="cannot read video.mp4"):
        signals.run(tmp_path, settings)


@needs_ffmpeg
def test_compute_signals_speed_on_60s_video(tmp_path):
    video = tmp_path / "video.mp4"
    _make_testsrc_video(video, duration=60)
    start = time.perf_counter()
    result = signals.compute_signals(video)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0
    assert result["duration_s"] == pytest.approx(60.0, abs=1.0)
    assert len(result["motion"]) >= 200


def _candidates(result):
    return signals.rank_candidates(
        find_pauses(result["motion"]) + find_scene_changes(result["scene"]),
        result["duration_s"],
    )
