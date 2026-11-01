"""Tests for the refine stage (Spark pass 2). Everything uses fakes."""

import json
import shutil
import subprocess
import types

import cv2
import pytest

from app import artifacts
from app.config import Settings
from app.meta_client import BudgetExceeded, MetaError
from app.pipeline import refine
from app.pipeline.refine import (
    RefineError,
    clip_window,
    make_timecoded_clip,
    refine_step,
    select_steps,
)
from app.schemas import (
    Analysis,
    DraftStep,
    Fusion,
    FusionStep,
    IngestInfo,
    Refine,
    Transcript,
    Turn,
)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
needs_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None, reason="ffprobe is not installed"
)


def _draft(title, start, end, confidence=0.9, screw_count=0):
    return DraftStep(
        title=title,
        instruction=f"Do {title}.",
        start_s=start,
        end_s=end,
        screw_count=screw_count,
        confidence=confidence,
    )


def _fusion(confidences, times=None):
    steps = []
    for i, confidence in enumerate(confidences, start=1):
        start, end = times[i - 1] if times else ((i - 1) * 10.0, i * 10.0)
        steps.append(
            FusionStep(
                index=i,
                start_s=start,
                end_s=end,
                start_source="spark",
                end_source="spark",
                agreement=1.0,
                confidence=confidence,
            )
        )
    return Fusion(candidates=0, steps=steps)


def _make_proxy(path, seconds=12, size="320x240", fps=15):
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={size}:rate={fps}:duration={seconds}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return path


def _probe_duration(path):
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return float(out.stdout.strip())


def _answer(start=2.5, end=7.5, confidence=0.9):
    return {
        "start_s": start,
        "end_s": end,
        "instruction": "Remove the back cover.",
        "action": "unscrew",
        "removes": ["back cover"],
        "screw_count": 3,
        "warnings": [],
        "confidence": confidence,
    }


class FakeClient:
    """Pipeline-level fake: records uploads, respond kwargs and deletions."""

    def __init__(self, results):
        self.results = list(results)
        self.uploaded = []
        self.deleted = []
        self.respond_calls = []

    def upload_file(self, path):
        self.uploaded.append(path)
        return "file-abc"

    def respond(self, **kwargs):
        self.respond_calls.append(kwargs)
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return types.SimpleNamespace(output_text=json.dumps(item))

    def delete_file(self, file_id):
        self.deleted.append(file_id)


def _settings(tmp_path):
    return Settings(model_api_key="", data_dir=tmp_path)


# --- 1. select_steps ----------------------------------------------------------


def test_select_steps_picks_low_confidence_and_screw_steps_lowest_first():
    analysis = Analysis(
        steps=[
            _draft("a", 0, 10, confidence=0.9),
            _draft("b", 10, 20, confidence=0.9, screw_count=2),
            _draft("c", 20, 30, confidence=0.9),
            _draft("d", 30, 40, confidence=0.9),
            _draft("e", 40, 50, confidence=0.9),
        ]
    )
    fusion = _fusion([0.9, 0.9, 0.5, 0.3, 0.55])
    # Fused confidence wins: c/d/e are uncertain, b has screws, a is out.
    assert select_steps(analysis, fusion) == [4, 3, 5, 2]


def test_select_steps_without_fusion_uses_draft_confidence_and_time_order():
    analysis = Analysis(
        steps=[
            _draft("late", 20, 30, confidence=0.4),
            _draft("early", 0, 10, confidence=0.9, screw_count=1),
            _draft("mid", 10, 20, confidence=0.9),
        ]
    )
    # Indexes are in time order: early=1 (screws), mid=2, late=3 (low confidence).
    assert select_steps(analysis, None) == [3, 1]


def test_select_steps_leaves_out_a_step_longer_than_the_clip():
    analysis = Analysis(
        steps=[_draft("long", 0, 99, confidence=0.3), _draft("short", 100, 110, confidence=0.3)]
    )
    assert select_steps(analysis, None) == [2]


def test_select_steps_caps_at_max_steps():
    analysis = Analysis(
        steps=[_draft(f"s{i}", i * 10, i * 10 + 10, confidence=0.1) for i in range(6)]
    )
    assert refine.MAX_STEPS == 4
    assert select_steps(analysis, None) == [1, 2, 3, 4]


# --- 2. clip_window -----------------------------------------------------------


def test_clip_window_pads_and_clamps():
    assert clip_window(10, 20, 60) == (8.0, 22.0)
    assert clip_window(0, 5, 60) == (0.0, 7.0)
    assert clip_window(55, 60, 60) == (53.0, 60.0)
    assert clip_window(0, 60, 60) == (15.0, 45.0)


def test_clip_window_centres_a_long_step():
    assert clip_window(10, 50, 100) == (15.0, 45.0)
    a, b = clip_window(30, 70, 80)
    assert (a, b) == (35.0, 65.0)
    assert b - a == refine.MAX_CLIP_S


# --- 3. timecoded clip --------------------------------------------------------


@needs_ffmpeg
@needs_ffprobe
def test_timecoded_clip_duration_size_and_timecode_pixels(tmp_path):
    proxy = _make_proxy(tmp_path / "video.mp4")
    dst = tmp_path / "clip.mp4"
    result = make_timecoded_clip(proxy, 1.0, 4.0, dst)
    assert result == dst
    assert _probe_duration(dst) == pytest.approx(3.0, abs=0.1)
    capture = cv2.VideoCapture(str(dst))
    assert capture.isOpened()
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    ok, frame = capture.read()
    capture.release()
    assert min(width, height) == 480
    assert ok and frame is not None
    # The timecode box sits top-left: mostly dark pixels with bright white text.
    box = frame[12:60, 12:170]
    assert (box < 50).mean() > 0.5
    assert (box > 200).mean() > 0.03


# --- 4/5/6. refine_step and run with a fake Spark -----------------------------


def test_refine_step_inside_window_keeps_answer_times(tmp_path):
    client = FakeClient([_answer(2.5, 7.5, confidence=0.9)])
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake")
    result = refine_step(
        client,
        _settings(tmp_path),
        clip,
        2,
        _draft("cover", 2, 8, screw_count=4),
        2.0,
        8.0,
        (0.0, 10.0),
        [Turn(start_s=3.0, end_s=4.0, text="now the cover")],
    )
    assert result.index == 2
    assert (result.start_s, result.end_s) == (2.5, 7.5)
    assert result.screw_count == 3
    assert result.confidence == 0.9
    assert client.deleted == ["file-abc"]
    kwargs = client.respond_calls[0]
    assert kwargs["max_output_tokens"] == 8000
    assert kwargs["timeout_s"] == 300
    assert kwargs["retry_timeouts"] is False
    assert kwargs["text"]["format"]["name"] == "refined_step"
    assert kwargs["text"]["format"]["strict"] is True


def test_refine_step_outside_window_is_rejected(tmp_path):
    client = FakeClient([_answer(20.0, 25.0, confidence=0.95)])
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake")
    with pytest.raises(RefineError, match="outside the clip"):
        refine_step(
            client, _settings(tmp_path), clip, 1, _draft("cover", 4, 6), 4.0, 6.0, (2.0, 8.0), []
        )


def test_refine_step_inverted_answer_is_rejected(tmp_path):
    client = FakeClient([_answer(6.0, 5.0, confidence=0.9)])
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake")
    with pytest.raises(RefineError, match="outside the clip"):
        refine_step(
            client, _settings(tmp_path), clip, 1, _draft("cover", 4, 6), 4.0, 6.0, (2.0, 8.0), []
        )


def _write_job(tmp_path, *, fused_confidences=(0.4,)):
    """One-step job: draft 2-8 s, fused 2-8 s, turns inside and outside."""
    analysis = Analysis(steps=[_draft("Remove cover", 2, 8, confidence=0.9, screw_count=4)])
    artifacts.save(tmp_path, analysis)
    artifacts.save(tmp_path, _fusion(list(fused_confidences), times=[(2.0, 8.0)]))
    artifacts.save(
        tmp_path,
        Transcript(
            mode="narrated",
            duration_s=12.0,
            turns=[
                Turn(start_s=3.0, end_s=4.0, text="inside turn words"),
                Turn(start_s=10.5, end_s=11.5, text="outside turn words"),
            ],
        ),
    )
    artifacts.save(
        tmp_path, IngestInfo(duration_s=12.0, width=320, height=240, has_audio=True, fps=15.0)
    )
    _make_proxy(tmp_path / "video.mp4")


@needs_ffmpeg
def test_run_prompt_has_title_draft_times_and_window_turns_only(tmp_path):
    _write_job(tmp_path)
    client = FakeClient([_answer(2.5, 7.5)])
    result = refine.run(tmp_path, _settings(tmp_path), client)
    assert len(result.steps) == 1
    assert (result.steps[0].start_s, result.steps[0].end_s) == (2.5, 7.5)
    prompt = client.respond_calls[0]["input"][0]["content"][0]["text"]
    assert "Remove cover" in prompt
    assert "2.0" in prompt and "8.0" in prompt
    assert "inside turn words" in prompt
    assert "outside turn words" not in prompt
    assert "<<" not in prompt
    assert client.deleted == ["file-abc"]
    assert artifacts.load(tmp_path, Refine) == result
    assert not (tmp_path / "refine").exists()  # temporary clips deleted


@needs_ffmpeg
def test_run_delete_called_and_failure_goes_to_skipped(tmp_path):
    _write_job(tmp_path)
    client = FakeClient([MetaError("boom")])
    result = refine.run(tmp_path, _settings(tmp_path), client)
    assert result.steps == []
    assert len(result.skipped) == 1
    assert "step 1" in result.skipped[0]
    assert client.deleted == ["file-abc"]
    assert artifacts.load(tmp_path, Refine) == result


@needs_ffmpeg
def test_run_bad_json_goes_to_skipped(tmp_path):
    _write_job(tmp_path)
    # FakeClient.respond wraps dicts; give it a raw-answer client instead.
    raw = FakeClient([_answer()])
    raw.respond = lambda **kwargs: types.SimpleNamespace(output_text="not json {{{")  # type: ignore[method-assign]
    result = refine.run(tmp_path, _settings(tmp_path), raw)
    assert result.steps == []
    assert len(result.skipped) == 1
    assert raw.deleted == ["file-abc"]


@needs_ffmpeg
def test_run_budget_exceeded_stops_cleanly(tmp_path):
    _write_job(tmp_path)
    client = FakeClient([BudgetExceeded("spend already at budget")])
    result = refine.run(tmp_path, _settings(tmp_path), client)
    assert result.steps == []
    assert len(client.respond_calls) == 1
    assert artifacts.load(tmp_path, Refine) == result


def test_run_with_nothing_to_refine_saves_empty_without_client(tmp_path):
    artifacts.save(tmp_path, Analysis(steps=[_draft("a", 0, 10, confidence=0.95)]))
    artifacts.save(
        tmp_path, IngestInfo(duration_s=12.0, width=320, height=240, has_audio=False, fps=15.0)
    )
    result = refine.run(tmp_path, _settings(tmp_path), client=None)
    assert result.steps == [] and result.skipped == []
    assert artifacts.load(tmp_path, Refine) == result
