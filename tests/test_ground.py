"""Grounding + SAM box-prompt tests. Everything uses a fake client, never the network."""

import json
import types
from pathlib import Path

import pytest

from app.config import Settings
from app.meta_client import (
    GROUND_SCHEMA,
    GroundBox,
    MetaClient,
    MetaError,
    sam_cost,
    to_pixels,
)


def make_settings(data_dir: Path) -> Settings:
    return Settings(
        model_api_key="test-key",
        data_dir=data_dir,
        budget_usd=120.0,
    )


class FakeResponses:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0
        self.kwargs: list[dict] = []

    def create(self, **kwargs):
        self.calls += 1
        self.kwargs.append(kwargs)
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, results):
        self.responses = FakeResponses(results)


def _write_test_image(path: Path, width: int = 100, height: int = 100) -> Path:
    import cv2
    import numpy as np

    image = np.full((height, width, 3), 120, dtype=np.uint8)
    assert cv2.imwrite(str(path), image)
    return path


def _ground_response(payload, output_tokens=100):
    return types.SimpleNamespace(
        output_text=json.dumps(payload) if not isinstance(payload, str) else payload,
        usage=types.SimpleNamespace(
            input_tokens=1000,
            input_tokens_details=types.SimpleNamespace(cached_tokens=0),
            output_tokens=output_tokens,
        ),
    )


def _ground_payload():
    return {
        "boxes": [
            {
                "label": "top-left screw",
                "x_min": 100,
                "y_min": 120,
                "x_max": 200,
                "y_max": 220,
                "why": "matches the described screw",
            },
            {
                "label": "bottom-right screw",
                "x_min": 500,
                "y_min": 500,
                "x_max": 640,
                "y_max": 660,
                "why": "second instance",
            },
        ]
    }


def _sam_fake_record(obj_id, x1, y1, x2, y2, img_w, img_h):
    from meta_sam_parser._mask_codec import _encode_raster

    mw, mh = x2 - x1 + 1, y2 - y1 + 1
    payload = _encode_raster([1] * (mw * mh), mw, mh)
    return (
        f"{obj_id}<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={img_w};h={img_h}|>"
        f"<|mask;x=0;y=0;data={mh},{mw},{payload}|>"
    )


def _sam_response(output_text):
    return types.SimpleNamespace(output_text=output_text, usage=None)


def test_ground_returns_two_boxes(tmp_path):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    fake = FakeClient([_ground_response(_ground_payload())])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    boxes = client.ground(image_path, "the loose screw", context="top-left corner")

    assert boxes == [
        GroundBox(
            label="top-left screw",
            box=(100, 120, 200, 220),
            why="matches the described screw",
        ),
        GroundBox(label="bottom-right screw", box=(500, 500, 640, 660), why="second instance"),
    ]
    assert all(isinstance(box, GroundBox) for box in boxes)


def test_ground_request_shape(tmp_path):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    fake = FakeClient([_ground_response({"boxes": []})])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    assert client.ground(image_path, "the loose screw", context="near the hinge") == []

    assert fake.responses.calls == 1
    kwargs = fake.responses.kwargs[0]
    assert kwargs["model"] == "muse-spark-1.3"
    assert kwargs["reasoning"] == {"effort": "medium"}
    assert kwargs["max_output_tokens"] == 12000
    assert kwargs["text"] == {
        "format": {
            "type": "json_schema",
            "name": "grounding",
            "schema": GROUND_SCHEMA,
            "strict": True,
        }
    }
    content = kwargs["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert "the loose screw" in content[0]["text"]
    assert "near the hinge" in content[0]["text"]
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/jpeg;base64,")
    with open(tmp_path / "spend.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["calls"] == 1


def test_ground_empty_context_sends_none(tmp_path):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    fake = FakeClient([_ground_response({"boxes": []})])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    client.ground(image_path, "the loose screw")

    prompt = fake.responses.kwargs[0]["input"][0]["content"][0]["text"]
    assert "Context: none" in prompt


def test_ground_clamps_coordinates(tmp_path):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    payload = {
        "boxes": [
            {
                "label": "edge",
                "x_min": -30,
                "y_min": -5,
                "x_max": 1200,
                "y_max": 2000,
                "why": "out of range",
            }
        ]
    }
    fake = FakeClient([_ground_response(payload)])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    assert client.ground(image_path, "screw") == [
        GroundBox(label="edge", box=(0, 0, 1000, 1000), why="out of range")
    ]


def test_ground_swaps_reversed_edges(tmp_path):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    payload = {
        "boxes": [
            {
                "label": "flipped",
                "x_min": 400,
                "y_min": 300,
                "x_max": 100,
                "y_max": 50,
                "why": "reversed",
            }
        ]
    }
    fake = FakeClient([_ground_response(payload)])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    assert client.ground(image_path, "screw") == [
        GroundBox(label="flipped", box=(100, 50, 400, 300), why="reversed")
    ]


def test_ground_drops_tiny_boxes(tmp_path):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    payload = {
        "boxes": [
            {
                "label": "speck",
                "x_min": 10,
                "y_min": 10,
                "x_max": 12,
                "y_max": 40,
                "why": "too narrow",
            },
            {
                "label": "sliver",
                "x_min": 10,
                "y_min": 10,
                "x_max": 60,
                "y_max": 12,
                "why": "too flat",
            },
            {
                "label": "real",
                "x_min": 10,
                "y_min": 10,
                "x_max": 60,
                "y_max": 60,
                "why": "big enough",
            },
        ]
    }
    fake = FakeClient([_ground_response(payload)])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    assert client.ground(image_path, "screw") == [
        GroundBox(label="real", box=(10, 10, 60, 60), why="big enough")
    ]


def test_ground_keeps_at_most_max_boxes(tmp_path):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    fake = FakeClient([_ground_response(_ground_payload())])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    boxes = client.ground(image_path, "screw", max_boxes=1)

    assert len(boxes) == 1
    assert boxes[0].label == "top-left screw"
    prompt = fake.responses.kwargs[0]["input"][0]["content"][0]["text"]
    assert "At most 1 boxes." in prompt


def test_ground_invalid_json_raises(tmp_path):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    fake = FakeClient([_ground_response("this is not json{{{")])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    with pytest.raises(MetaError, match="grounding returned invalid JSON"):
        client.ground(image_path, "screw")
    assert fake.responses.calls == 1


def test_ground_rejects_empty_query_without_call(tmp_path):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    fake = FakeClient([_ground_response({"boxes": []})])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    with pytest.raises(ValueError):
        client.ground(image_path, "   ")
    assert fake.responses.calls == 0


def test_to_pixels_edges():
    assert to_pixels((0, 0, 1000, 1000), 100, 80) == (0, 0, 99, 79)
    assert to_pixels((0, 0, 1000, 1000), 1, 1) == (0, 0, 0, 0)
    assert to_pixels((100, 200, 300, 400), 100, 80) == (10, 16, 30, 32)


def test_to_pixels_rejects_bad_input():
    with pytest.raises(ValueError):
        to_pixels((0, 0, 1000), 100, 80)
    with pytest.raises(ValueError):
        to_pixels((0, 0, 1000, 1000), 0, 80)


def test_segment_boxes_sends_zero_frame_box_prompt(tmp_path):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    answer = "<0f>" + ",".join(
        [
            _sam_fake_record(1, 10, 10, 29, 29, 100, 100),
            _sam_fake_record(2, 50, 50, 59, 59, 100, 100),
        ]
    )
    fake = FakeClient([_sam_response(answer)])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    detections, size = client.segment_boxes(
        image_path, [(100, 100, 300, 300), (500, 500, 900, 900)]
    )

    assert size == (100, 100)
    assert [d.object_id for d in detections] == ["1", "2"]
    assert fake.responses.calls == 1
    kwargs = fake.responses.kwargs[0]
    assert kwargs["model"] == "sam-3.1"
    assert kwargs["metadata"] == {"include_confidence": "true"}
    content = kwargs["input"][0]["content"]
    assert "<0f>1<|box;" in content[0]["text"]
    assert "w=100;h=100" in content[0]["text"]
    assert "2<|box;" in content[0]["text"]
    assert content[1]["type"] == "input_image"
    with open(tmp_path / "spend.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["total_usd"] == pytest.approx(sam_cost(images=1))


@pytest.mark.parametrize("count", [0, 17])
def test_segment_boxes_rejects_bad_counts(tmp_path, count):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    fake = FakeClient([_sam_response("")])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    with pytest.raises(ValueError):
        client.segment_boxes(image_path, [(0, 0, 500, 500)] * count)
    assert fake.responses.calls == 0
