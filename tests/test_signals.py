"""Tests for the visual-signals stage."""

import json
import shutil
import subprocess
import time

import cv2
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


def _make_vfr_video(path):
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x568:rate=60:duration=4",
            "-vf",
            "setpts='if(lt(N,120),N/(60*TB),(120+(N-120)*2)/(60*TB))'",
            "-fps_mode",
            "vfr",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )


def _make_shake_video(path, still_path):
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=360x608:rate=1:duration=1",
            "-frames:v",
            "1",
            str(still_path),
        ]
    )
    _run_ffmpeg(
        [
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(still_path),
            "-vf",
            "crop=320:568:x='20+6*sin(1.7*n)':y='20+5*cos(1.3*n)'",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )


def _ffprobe_pts(path):
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "frame=pts_time",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return [float(line.strip().rstrip(",")) for line in out.stdout.splitlines() if line.strip()]


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
    assert len(pauses) == 1
    assert pauses[0]["score"] == 1.0


def test_find_pauses_constant_accelerating_motion_has_no_pause():
    motion = [[i * 0.25, 0.2 + 0.01 * i] for i in range(32)]
    assert find_pauses(motion) == []


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
def test_vfr_sample_timestamps_match_ffprobe_pts(tmp_path):
    video = tmp_path / "video.mp4"
    _make_vfr_video(video)
    pts = _ffprobe_pts(video)
    samples = list(signals.sample_frames(video))
    assert len(samples) >= 10
    for t_seconds, _frame in samples:
        nearest = min(abs(t_seconds - p) for p in pts)
        assert nearest <= 0.05, t_seconds


@needs_ffmpeg
def test_shake_only_compensated_energy_is_much_lower_than_raw(tmp_path):
    video = tmp_path / "video.mp4"
    _make_shake_video(video, tmp_path / "still.png")
    result = signals.compute_signals(video)
    compensated = [value for _t, value in result.motion]
    raw = []
    prev_gray = None
    for _t, frame in signals.sample_frames(video):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if prev_gray is None:
            raw.append(0.0)
        else:
            raw.append(float(cv2.absdiff(gray, prev_gray).mean()) / 255.0)
        prev_gray = gray
    comp_mean = sum(compensated) / len(compensated)
    raw_mean = sum(raw) / len(raw)
    print(f"shake compensated={comp_mean:.5f} raw={raw_mean:.5f}")
    assert raw_mean > 0
    assert comp_mean < 0.30 * raw_mean


@needs_ffmpeg
def test_pause_candidate_in_synthetic_video(tmp_path):
    video = tmp_path / "video.mp4"
    _make_pause_video(video)
    result = signals.compute_signals(video)
    pauses = [c for c in result.candidates if c.kind == "pause"]
    assert len(pauses) == 1
    assert 3.0 <= pauses[0].t <= 5.0


@needs_ffmpeg
def test_scene_candidate_in_synthetic_video(tmp_path):
    video = tmp_path / "video.mp4"
    _make_scene_video(video)
    result = signals.compute_signals(video)
    scenes = [c for c in result.candidates if c.kind == "scene"]
    assert len(scenes) == 1
    assert 1.5 <= scenes[0].t <= 2.5


@needs_ffmpeg
def test_run_writes_signals_json(tmp_path):
    _make_scene_video(tmp_path / "video.mp4")
    settings = Settings(model_api_key="", data_dir=tmp_path)
    result = signals.run(tmp_path, settings)
    assert result.fps == 4
    assert result.duration_s == pytest.approx(4.0, abs=0.5)
    assert result.motion[0][1] == 0.0
    assert result.scene[0][1] == 0.0
    stored = json.loads((tmp_path / "signals.json").read_text(encoding="utf-8"))
    assert stored == result.model_dump(mode="json")


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
    assert result.duration_s == pytest.approx(60.0, abs=1.0)
    assert len(result.motion) >= 200
