"""Build realistic phone-video fixtures with ffmpeg (no files committed).

Each function writes a tiny synthetic clip that imitates one property of a real
phone recording: variable frame rate, HDR colour or a rotation tag. The recipes
for those properties were verified on this machine; see tasks/018-media-ladder.md.
"""

import subprocess
from pathlib import Path


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def make_video(
    path: Path,
    *,
    size: tuple[int, int] = (1080, 1920),
    fps: int = 30,
    seconds: int = 3,
    audio: bool = True,
    vfr: bool = False,
    hdr: bool = False,
    rotation: int = 0,
) -> Path:
    """Write a synthetic clip to ``path`` and return it.

    ``size`` is the encoded size. With ``rotation`` 90/270 the encoded frame is
    landscape and the tag turns it portrait on display, like a phone does.
    With ``vfr`` the clip runs at 60 fps for the first 60 frames and at half
    rate afterwards. With ``hdr`` the clip is 10-bit HLG BT.2020 HEVC (.mov).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    if rotation % 360 in (90, 270) and width < height:
        width, height = height, width
    src_fps = 60 if vfr else fps
    base = path.with_suffix(".base.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={width}x{height}:rate={src_fps}:duration={seconds}",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    if vfr:
        cmd += ["-vf", "setpts='if(lt(N,60),N/(60*TB),(60+(N-60)*2)/(60*TB))'", "-fps_mode", "vfr"]
    cmd += ["-t", str(seconds), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-shortest"] if audio else ["-an"]
    cmd += [str(base)]
    try:
        _run(cmd)
        current = base
        if hdr:
            hdr_path = path.with_suffix(".hdr.mov")
            cmd = [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(current),
                "-vf",
                "colorspace=all=bt2020:iall=bt709:format=yuv420p10",
                "-c:v",
                "libx265",
                "-x265-params",
                "log-level=error:colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc",
                "-pix_fmt",
                "yuv420p10le",
                "-tag:v",
                "hvc1",
            ]
            cmd += ["-c:a", "copy"] if audio else ["-an"]
            cmd += [str(hdr_path)]
            _run(cmd)
            current = hdr_path
        if rotation % 360:
            rotated = path.with_suffix(".rot.mov")
            _run(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-display_rotation",
                    str(rotation % 360),
                    "-i",
                    str(current),
                    "-c",
                    "copy",
                    str(rotated),
                ]
            )
            current = rotated
        if current != path:
            current.replace(path)
    finally:
        base.unlink(missing_ok=True)
        path.with_suffix(".hdr.mov").unlink(missing_ok=True)
        path.with_suffix(".rot.mov").unlink(missing_ok=True)
    return path
