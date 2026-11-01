"""The spoken voice: Meta's open-weights MMS-TTS English model, run on this machine.

Muse Voice only transcribes, so speech comes from Meta's open model (CC-BY-NC 4.0, no Model API
call and no credits). It reads sentence by sentence because it ignores punctuation, and it only
knows letters, so numbers are spelled out first. Every line is kept as a WAV in the job's
``voice/`` folder. Without the model (``scripts/get_voice.py``) the pages use the device voice.
"""

import hashlib
import re
import threading
import wave
from pathlib import Path
from typing import Any

import numpy as np

from app import artifacts
from app.config import Settings

MAX_TEXT = 1500
MAX_FILES_PER_JOB = 3000
PAUSE_S = 0.28
SPEED = 0.95

ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
).split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()

_engine: Any = None
_engine_dir: Path | None = None
_lock = threading.Lock()


class VoiceError(Exception):
    """The line could not be spoken; the page falls back to the device voice."""


def ready(settings: Settings, language: str | None) -> bool:
    """True when the model is installed and the guide is in English."""
    english = (language or "en").lower().split("-")[0] == "en"
    return english and (settings.voice_model_dir / "model.onnx").is_file()


def number_words(number: int) -> str:
    """12 -> "twelve", 345 -> "three hundred forty five"; digit by digit from 10000 up."""
    if number < 20:
        return ONES[number]
    if number < 100:
        return TENS[number // 10] + (f" {ONES[number % 10]}" if number % 10 else "")
    if number < 1000:
        rest = f" {number_words(number % 100)}" if number % 100 else ""
        return f"{ONES[number // 100]} hundred{rest}"
    if number < 10000:
        rest = f" {number_words(number % 1000)}" if number % 1000 else ""
        return f"{ONES[number // 1000]} thousand{rest}"
    return " ".join(ONES[int(digit)] for digit in str(number))


def clean(sentence: str) -> str:
    """Only what the model can read: lower-case letters, apostrophes and spoken numbers."""
    text = re.sub(r"(\d)\s*mm\b", r"\1 millimeters", sentence.lower())
    text = re.sub(r"(\d)\s*%", r"\1 percent", text)
    text = re.sub(r"\d+", lambda m: f" {number_words(int(m.group()))} ", text)
    text = text.replace("’", "'")
    text = re.sub(r"[^a-z' ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def sentences(text: str) -> list[str]:
    """The text cut at its stops, cleaned; empty pieces dropped."""
    pieces = re.split(r"(?<=[.!?…;:])\s+|\n+", text)
    return [line for line in (clean(piece) for piece in pieces) if line]


def _load(settings: Settings) -> Any:
    """The model, loaded once."""
    global _engine, _engine_dir
    folder = settings.voice_model_dir
    if _engine is None or _engine_dir != folder:
        import sherpa_onnx  # a heavy import, only when something is spoken

        vits = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=str(folder / "model.onnx"), lexicon="", tokens=str(folder / "tokens.txt")
        )
        model = sherpa_onnx.OfflineTtsModelConfig(vits=vits, num_threads=4)
        _engine = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=model))
        _engine_dir = folder
    return _engine


def _synthesize(settings: Settings, lines: list[str]) -> tuple[np.ndarray, int]:
    """All the lines as 16-bit samples with a short pause between them."""
    chunks: list[np.ndarray] = []
    rate = 16000
    with _lock:  # one model, one line at a time
        engine = _load(settings)
        for line in lines:
            audio = engine.generate(line, sid=0, speed=SPEED)
            rate = audio.sample_rate
            chunks.append(np.array(audio.samples, dtype=np.float32))
            chunks.append(np.zeros(int(rate * PAUSE_S), dtype=np.float32))
    pcm = np.clip(np.concatenate(chunks), -1, 1) * 32767
    return pcm.astype(np.int16), rate


def speak(job_dir: Path, settings: Settings, text: str) -> Path:
    """The WAV of ``text``, made once and kept in the job's folder."""
    if not ready(settings, "en"):
        raise VoiceError("the voice model is not installed")
    if len(text) > MAX_TEXT:
        raise VoiceError(f"text is too long (max {MAX_TEXT} characters)")
    lines = sentences(text)
    if not lines:
        raise VoiceError("nothing to say")
    name = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:24]
    target = job_dir / "voice" / f"{name}.wav"
    if target.is_file():
        return target
    folder = target.parent
    if folder.is_dir() and sum(1 for _ in folder.glob("*.wav")) >= MAX_FILES_PER_JOB:
        raise VoiceError("voice limit reached for this job")
    try:
        pcm, rate = _synthesize(settings, lines)
        with artifacts.atomic_path(target) as tmp, wave.open(str(tmp), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(pcm.tobytes())
    except (OSError, RuntimeError, ValueError) as exc:
        raise VoiceError(f"could not make the voice: {exc}") from exc
    return target
