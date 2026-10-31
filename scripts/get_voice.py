"""Download Meta's open-weights English voice (MMS-TTS, CC-BY-NC 4.0) to the voice model folder.

Run: ``python -m scripts.get_voice``. About 107 MB; nothing else in FixScribe needs it.
"""

import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from app.config import get_settings

URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-mms-eng.tar.bz2"
WANTED = ("model.onnx", "tokens.txt")


def main() -> int:
    target = get_settings().voice_model_dir
    if all((target / name).is_file() for name in WANTED):
        print(f"already there: {target}")
        return 0
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "voice.tar.bz2"
        urllib.request.urlretrieve(URL, archive)
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                name = Path(member.name).name
                source = tar.extractfile(member) if member.isfile() else None
                if name in WANTED and source is not None:
                    (target / name).write_bytes(source.read())
    missing = [name for name in WANTED if not (target / name).is_file()]
    if missing:
        print(f"missing from the download: {missing}", file=sys.stderr)
        return 1
    print(f"voice installed in {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
