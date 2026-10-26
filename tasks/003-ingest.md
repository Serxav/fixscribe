# Task 003: ingest
Branch: feat/ingest
Owner: Muse Code

## Goal
First pipeline stage: take the uploaded video in a job folder, check it, convert it to a 720p
mp4 and extract the audio as WAV mono 16-bit 24 kHz for transcription. No Meta calls.

## Why this matters for judging
Demo + Impact: real phone videos (portrait, .mov, any size) must just work when a technician uploads them, and a too-long or broken video must give a clear message instead of a crash.

## Files to touch
- `app/pipeline/ingest.py`
- `tests/test_ingest.py` (new)

## Do not touch
- Everything else. In particular `app/meta_client.py`, `app/jobs.py`, `app/schemas.py`,
  `app/pipeline/runner.py` (Claude Code is writing it), `pyproject.toml`, `.env*`.
- No new dependencies: call `ffmpeg` / `ffprobe` with `subprocess.run` (list of args, never
  `shell=True`).

## What to build (`app/pipeline/ingest.py`)
The runner will call **only** `run(job_dir, settings)`. Keep that signature exactly.

- `class IngestError(Exception)` — a clear message for the user, e.g. `"video too long: 612 s (max 600 s)"`.
- `@dataclass(frozen=True) class VideoInfo`: `duration_s: float`, `width: int`, `height: int`, `has_audio: bool`.
- `find_original(job_dir: Path) -> Path` — the one file named `original.*` in `job_dir`
  (the upload route saves it as `original.mp4`, `original.mov`, …). None or more than one → `IngestError`.
- `probe(path: Path) -> VideoInfo` — `ffprobe -v error -show_streams -show_format -of json <path>`.
  `width`/`height` from the first `codec_type == "video"` stream, `has_audio` = any `codec_type == "audio"`
  stream, `duration_s` from `format.duration`. No video stream or ffprobe fails → `IngestError("not a readable video")`.
  Note: phones store portrait videos as landscape + a rotation tag. Use the size **after** rotation:
  if the video stream has `side_data_list[].rotation` of 90 or -90 (or `tags.rotate` "90"/"270"), swap width and height.
- `normalize_video(src: Path, dst: Path) -> None` — 720p mp4, never upscaled:
  ```
  ffmpeg -y -v error -i SRC
    -vf scale=w='if(gt(iw,ih),-2,min(720,iw))':h='if(gt(iw,ih),min(720,ih),-2)'
    -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p
    -c:a aac -b:a 128k -movflags +faststart DST
  ```
  (landscape → height 720, portrait → width 720; the short side is at most 720.)
  Keep the audio track in the mp4 (`-c:a aac`); if the source has no audio, ffmpeg just skips it.
- `extract_audio(src: Path, dst: Path) -> None` —
  `ffmpeg -y -v error -i SRC -vn -ac 1 -ar 24000 -c:a pcm_s16le DST`
  (format required by https://dev.meta.ai/docs/speech-to-text: WAV, mono, 16-bit PCM, 16 or 24 kHz,
  max 10 minutes, max 32 MB per request; 10 min at 24 kHz is 28.8 MB, so it fits.)
- `run_ffmpeg(args: list[str], timeout_s: int = 600) -> None` — one helper used by both functions:
  - `FileNotFoundError` (ffmpeg not installed) → `IngestError("ffmpeg is not installed")`
  - `subprocess.TimeoutExpired` → `IngestError("ffmpeg took too long")`
  - non-zero exit → `IngestError` with the **last 3 lines** of stderr.
- `run(job_dir: Path, settings: Settings) -> VideoInfo`:
  1. `src = find_original(job_dir)`, `info = probe(src)`.
  2. `info.duration_s > settings.max_video_seconds` → `IngestError` (before any conversion).
  3. Write `video.mp4` and, only if `info.has_audio`, `audio.wav`. **Atomic**: ffmpeg writes to
     `video.tmp.mp4` / `audio.tmp.wav` in the same folder, then `os.replace` to the final name.
     On error, delete the tmp file.
  4. Write `ingest.json` atomically (temp file + `os.replace`):
     `{"duration_s": 12.0, "width": 720, "height": 1280, "has_audio": true}` — size of `video.mp4`
     (probe it after converting).
  5. Return the `VideoInfo` of `video.mp4`.

## Docs
- Audio format and limits: https://dev.meta.ai/docs/speech-to-text
- Video must be mp4 for Muse Spark: https://dev.meta.ai/docs/video-understanding

## Done when
- `.venv/bin/pytest -q` passes; `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` are clean.
- `tests/test_ingest.py` makes its own tiny videos with ffmpeg in `tmp_path` (2 seconds, no files
  committed). Example, landscape with sound:
  ```
  ffmpeg -y -v error -f lavfi -i testsrc=size=1920x1080:rate=30 -f lavfi -i sine=frequency=440
    -t 2 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest original.mp4
  ```
  Tests (put `pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")` at the top):
  1. Landscape 1920x1080 with audio → `video.mp4` is 1280x720, `audio.wav` exists, and its header
     is mono / 24000 Hz / 16-bit (check with the `wave` module from the standard library), `ingest.json` matches.
  2. Portrait 1080x1920 → 720x1280.
  3. Small 640x360 → stays 640x360 (no upscale).
  4. No audio (`-an`, no sine input) → no `audio.wav`, `has_audio` false.
  5. `.mov` input (`original.mov`) works.
  6. `max_video_seconds=1` with a 2 s video → `IngestError` with "too long", and no `video.mp4`.
  7. A text file named `original.mp4` → `IngestError`, and no `*.tmp.*` file left.
  8. No `original.*` → `IngestError`; two of them → `IngestError`.
  9. `run_ffmpeg` with ffmpeg missing (monkeypatch `subprocess.run` to raise `FileNotFoundError`) → `IngestError`.
- Build `Settings` in tests with `Settings(model_api_key="", data_dir=tmp_path, max_video_seconds=...)`.

## Notes
Keep each function short. Tests must not take more than a few seconds in total: always 2-second clips.
