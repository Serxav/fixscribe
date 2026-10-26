# Task 018: media-ladder (real phone video in, clean working media out)
Branch: feat/media-ladder
Owner: Muse Code (muse-wonder-1.0)

## Goal
Make ingest correct for real phone video: constant frame rate with true timestamps, HDR converted
to SDR, rotation kept right, and the **native original** kept for stills (SAM and keyframes need
the pixels). Add a realistic video fixture factory so these cases are tested forever.
Audit findings F1, F2, F3, F12, F15 in `tasks/AUDIT_FOUNDATIONS.md` — read it, and
`docs/ENGINEERING_STANDARD.md`, before you start.

## Why this matters for judging
Technical depth + Impact: judges will upload their own iPhone videos (VFR, HDR, rotated, 60 fps).
Today those break our timestamps by up to 1.3 s and lose 25 % of the colour. This is the base
every model call stands on.

## Files to touch
- `app/pipeline/ingest.py` (rewrite as needed)
- `app/pipeline/media.py` (new: stills from the original)
- `tests/video_factory.py` (new), `tests/test_ingest.py`, `tests/test_media.py` (new)

## Do not touch
`app/schemas.py` (use `IngestInfo` and `SourceVideo` as they are), `app/artifacts.py`,
`app/pipeline/signals.py`, `scenes.py`, `runner.py`, every other stage, `pyproject.toml`, `.env*`.
No new dependencies. No web tools.

## Facts measured by Claude Code on this Mac
- ffmpeg here has `colorspace`, `tonemap`, `scale`, `libx264`, `libx265`, `hevc_videotoolbox`; it does
  **not** have `zscale`, `drawtext` or `libplacebo`.
- A VFR source (60 fps then 30 fps) keeps VFR through today's ingest (`avg_frame_rate` 7200/199 vs
  `r_frame_rate` 60/1); OpenCV then reports fps 36.18 and `frame_index / fps` is off by 1.3 s.
- A synthetic HLG BT.2020 10-bit HEVC clip comes out of today's ingest as 8-bit still tagged
  BT.2020/HLG and decodes 25 % less saturated than its SDR twin.
- Rotation tags already work (1920×1080 + 90° → 720×1280). Keep that.

## What to build
### `app/pipeline/ingest.py`
- `probe_source(path) -> SourceVideo` (model in `app/schemas.py`): display width/height after
  rotation, `rotation`, `fps` (from `avg_frame_rate`), `vfr` (true when the packet time deltas of the
  first ~300 video packets vary by more than 10 % of their median, from
  `ffprobe -select_streams v -show_entries packet=pts_time`), `codec`, `pix_fmt`, `color_transfer`,
  `color_primaries`, `hdr` (transfer `arib-std-b67` or `smpte2084`, or primaries `bt2020`), `duration_s`.
- `normalize_video(src, dst, source: SourceVideo)`: one ffmpeg command that
  - outputs **constant frame rate** `OUT_FPS = 30` (`-fps_mode cfr -r 30`; if the source is below 30 fps, keep its rounded rate, never below 15),
  - scales so the short side is at most 720 (never upscale, as today),
  - converts HDR to SDR BT.709 with the filters we have (start with
    `colorspace=all=bt709:iall=bt2020:fast=1:format=yuv420p`; you may try a better chain with
    `tonemap` — choose by measurement, see tests) and tags the output
    `-color_primaries bt709 -color_trc bt709 -colorspace bt709`,
  - uses a short GOP (`-g 60`) so seeking stays fast,
  - keeps the audio as AAC (as today).
- `run(job_dir, settings) -> IngestInfo`: keep today's checks (one `original.*`, duration limit,
  atomic temp files, WAV mono 16-bit 24 kHz), write `IngestInfo` with `fps` and `source` through
  `app.artifacts.save`. **Never delete or modify the original.**
### `app/pipeline/media.py`
- `extract_still(original: Path, source: SourceVideo, t: float, dst: Path, max_side: int | None = None) -> tuple[int, int]`
  — one frame at time `t` from the **original** at native resolution (or capped to `max_side`),
  rotation applied, HDR converted with the same colour chain as ingest, written atomically as PNG
  (`ffmpeg -ss T -i ORIGINAL -frames:v 1 ...`). Returns `(width, height)`.
- `extract_stills(original, source, times, out_dir, max_side=None) -> list[Path]`.
### `tests/video_factory.py`
Small functions that build realistic fixtures with ffmpeg in `tmp_path`: `make_video(path, *,
size=(1080, 1920), fps=30, seconds=3, audio=True, vfr=False, hdr=False, rotation=0)`. Use these
recipes (verified by Claude Code):
- VFR: `-vf "setpts='if(lt(N,60),N/(60*TB),(60+(N-60)*2)/(60*TB))'" -fps_mode vfr` on a 60 fps source.
- HDR: `-vf "colorspace=all=bt2020:iall=bt709:format=yuv420p10" -c:v libx265 -x265-params "log-level=error:colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc" -pix_fmt yuv420p10le -tag:v hvc1` into a `.mov`.
- Rotation: make a landscape file, then `ffmpeg -display_rotation 90 -i in.mp4 -c copy out.mov`.

## Done when
- `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .` pass.
- Tests with the factory (each one a clear behavioural assertion):
  1. VFR source → `probe_source(...).vfr is True`; after ingest `avg_frame_rate == r_frame_rate == 30/1`,
     duration within 0.1 s of the source, and OpenCV `frame_index / fps` matches `CAP_PROP_POS_MSEC` within 0.05 s on every frame.
  2. HDR source → `hdr is True`; output tagged BT.709; mean HSV saturation of a frame at 1.5 s within
     15 % of the same frame from the SDR twin (today it is −25 %). Put the measured numbers in your report.
  3. Rotated source → `rotation == 90`, `IngestInfo` 720×1280, `extract_still` returns 1080×1920 portrait.
  4. 60 fps source → output 30 fps.
  5. `extract_still` from an HDR original has saturation within 15 % of the SDR twin's still.
  6. The original file is byte-identical after ingest; `ingest.json` loads with `artifacts.load(job_dir, IngestInfo)`.
  7. Existing ingest tests still pass (adapt them to the new signatures).
- Report: the measured saturation numbers, ingest time for a 60 s 1080×1920 clip, and which HDR chain you chose and why.
