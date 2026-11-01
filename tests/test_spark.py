"""Spark helper and atomic-write tests. Everything uses fakes, never the network."""

import base64
import json
import types
from pathlib import Path

import pytest

from app.artifacts import atomic_path, write_bytes_atomic, write_text_atomic
from app.config import Settings
from app.spark import SparkAnswerError, ask_json, image_block, json_format


def _settings(tmp_path: Path) -> Settings:
    return Settings(model_api_key="", data_dir=tmp_path)


class FakeSparkClient:
    """Pipeline-level fake: records uploads, respond kwargs and deletions."""

    def __init__(self, results):
        self.results = list(results)
        self.uploaded: list[Path] = []
        self.deleted: list[str] = []
        self.respond_calls: list[dict] = []

    def upload_file(self, path):
        self.uploaded.append(Path(path))
        return "file-abc"

    def respond(self, **kwargs):
        self.respond_calls.append(kwargs)
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return types.SimpleNamespace(output_text=item)

    def delete_file(self, file_id):
        self.deleted.append(file_id)


def test_json_format_shape():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    assert json_format("repair_analysis", schema) == {
        "format": {
            "type": "json_schema",
            "name": "repair_analysis",
            "schema": schema,
            "strict": True,
        }
    }


def test_image_block_png(tmp_path):
    path = tmp_path / "still.png"
    path.write_bytes(b"fake-png-bytes")
    block = image_block(path)
    assert block["type"] == "input_image"
    expected = "data:image/png;base64," + base64.b64encode(b"fake-png-bytes").decode("ascii")
    assert block["image_url"] == expected


def test_image_block_jpg_uses_jpeg_mime(tmp_path):
    for suffix in (".jpg", ".jpeg"):
        path = tmp_path / f"photo{suffix}"
        path.write_bytes(b"fake-jpg-bytes")
        block = image_block(path)
        assert block["image_url"].startswith("data:image/jpeg;base64,")


def test_image_block_rejects_unknown_suffix(tmp_path):
    path = tmp_path / "photo.gif"
    path.write_bytes(b"fake")
    with pytest.raises(ValueError, match="unsupported image type"):
        image_block(path)


def test_ask_json_text_only(tmp_path):
    client = FakeSparkClient([json.dumps({"title": "ok"})])

    result = ask_json(
        client,
        _settings(tmp_path),
        name="repair_analysis",
        schema={"type": "object"},
        prompt="do the repair",
    )

    assert result == {"title": "ok"}
    assert client.uploaded == []
    assert client.deleted == []
    assert len(client.respond_calls) == 1
    kwargs = client.respond_calls[0]
    assert kwargs["model"] == "muse-spark-1.3"
    assert kwargs["max_output_tokens"] == 12000
    assert kwargs["text"] == json_format("repair_analysis", {"type": "object"})
    assert len(kwargs["input"]) == 1
    assert kwargs["input"][0]["role"] == "user"
    (text_block,) = kwargs["input"][0]["content"]
    assert text_block == {"type": "input_text", "text": "do the repair"}


def test_ask_json_images_come_after_text(tmp_path):
    paths = []
    for index in range(2):
        path = tmp_path / f"still_{index}.png"
        path.write_bytes(bytes([index + 1]) * 8)
        paths.append(path)
    client = FakeSparkClient([json.dumps({"object_name": "phone"})])

    ask_json(
        client,
        _settings(tmp_path),
        name="repair_identity",
        schema={"type": "object"},
        prompt="look at this",
        images=paths,
        max_output_tokens=4000,
        timeout_s=120.0,
    )

    (message,) = client.respond_calls[0]["input"]
    text_block, *image_blocks = message["content"]
    assert text_block == {"type": "input_text", "text": "look at this"}
    assert len(image_blocks) == 2
    for block, path in zip(image_blocks, paths, strict=True):
        assert block == image_block(path)
    assert client.respond_calls[0]["timeout_s"] == 120.0


def test_ask_json_video_uploads_and_deletes(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake-video")
    client = FakeSparkClient([json.dumps({"start_s": 1.0})])

    result = ask_json(
        client,
        _settings(tmp_path),
        name="refined_step",
        schema={"type": "object"},
        prompt="re-read this step",
        video=clip,
        retry_timeouts=False,
    )

    assert result == {"start_s": 1.0}
    assert client.uploaded == [clip]
    assert client.deleted == ["file-abc"]
    (message,) = client.respond_calls[0]["input"]
    text_block, file_block = message["content"]
    assert text_block == {"type": "input_text", "text": "re-read this step"}
    assert file_block == {"type": "input_file", "file_id": "file-abc"}
    assert client.respond_calls[0]["retry_timeouts"] is False


def test_ask_json_deletes_video_even_when_respond_raises(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake-video")
    client = FakeSparkClient([RuntimeError("boom")])

    with pytest.raises(RuntimeError, match="boom"):
        ask_json(
            client,
            _settings(tmp_path),
            name="refined_step",
            schema={"type": "object"},
            prompt="re-read this step",
            video=clip,
        )

    assert client.uploaded == [clip]
    assert client.deleted == ["file-abc"]


def test_ask_json_bad_json_raises_but_writes_raw(tmp_path):
    raw_path = tmp_path / "analysis_raw.txt"
    client = FakeSparkClient(["not json {{{"])

    with pytest.raises(SparkAnswerError, match="invalid JSON for repair_analysis"):
        ask_json(
            client,
            _settings(tmp_path),
            name="repair_analysis",
            schema={"type": "object"},
            prompt="do the repair",
            raw_path=raw_path,
        )

    assert raw_path.read_text(encoding="utf-8") == "not json {{{"


def test_ask_json_empty_answer_raises(tmp_path):
    client = FakeSparkClient([""])

    with pytest.raises(SparkAnswerError):
        ask_json(client, _settings(tmp_path), name="step", schema={"type": "object"}, prompt="go")


def test_atomic_path_success_replaces_and_keeps_suffix(tmp_path):
    dst = tmp_path / "sub" / "clip.mp4"
    seen: list[Path] = []
    with atomic_path(dst) as tmp:
        seen.append(tmp)
        assert tmp.parent == dst.parent
        assert tmp.suffix == ".mp4"
        assert tmp.name.startswith(".")
        tmp.write_bytes(b"new")

    assert dst.read_bytes() == b"new"
    assert list(tmp_path.rglob(".*.tmp.*")) == []
    assert seen[0].name == ".clip.tmp.mp4"


def test_atomic_path_exception_keeps_old_file_and_no_temp(tmp_path):
    dst = tmp_path / "photo.jpg"
    dst.write_bytes(b"old")

    with pytest.raises(RuntimeError, match="boom"):
        with atomic_path(dst) as tmp:
            tmp.write_bytes(b"new")
            raise RuntimeError("boom")

    assert dst.read_bytes() == b"old"
    assert list(tmp_path.rglob(".*.tmp.*")) == []


def test_write_bytes_and_text_atomic(tmp_path):
    blob = tmp_path / "nested" / "clip.mp4"
    write_bytes_atomic(blob, b"\x00\x01")
    assert blob.read_bytes() == b"\x00\x01"

    text_path = tmp_path / "analysis_raw.txt"
    write_text_atomic(text_path, "hola — adiós")
    assert text_path.read_text(encoding="utf-8") == "hola — adiós"
    assert list(tmp_path.rglob(".*.tmp.*")) == []
