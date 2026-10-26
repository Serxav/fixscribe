"""First-call script tests. Everything uses fakes, never the network."""

import pytest

from scripts.first_call import build_input, compare_steps, main, parse_steps


def test_build_input_shape():
    result = build_input("file-123")
    assert len(result) == 1
    assert result[0]["role"] == "user"
    text_block, file_block = result[0]["content"]
    assert text_block["type"] == "input_text"
    assert isinstance(text_block["text"], str) and text_block["text"]
    assert file_block == {"type": "input_file", "file_id": "file-123"}


def test_parse_steps_plain_json():
    text = '{"steps": [{"title": "Remove back cover", "start_s": 3.0, "end_s": 15.5}]}'
    assert parse_steps(text) == [{"title": "Remove back cover", "start_s": 3.0, "end_s": 15.5}]


def test_parse_steps_fenced_json():
    text = 'Here you go:\n```json\n{"steps": [{"title": "A", "start_s": 0, "end_s": 2}]}\n```'
    assert parse_steps(text) == [{"title": "A", "start_s": 0, "end_s": 2}]


def test_parse_steps_broken_text():
    with pytest.raises(ValueError, match="model did not return valid steps JSON"):
        parse_steps("not json at all {{{")


def test_parse_steps_bad_bounds():
    with pytest.raises(ValueError, match="model did not return valid steps JSON"):
        parse_steps('{"steps": [{"title": "A", "start_s": 5.0, "end_s": 5.0}]}')
    with pytest.raises(ValueError, match="model did not return valid steps JSON"):
        parse_steps('{"steps": [{"title": "A", "start_s": 7.0, "end_s": 2.0}]}')
    with pytest.raises(ValueError, match="model did not return valid steps JSON"):
        parse_steps('{"steps": [{"title": "A", "start_s": -1.0, "end_s": 2.0}]}')
    with pytest.raises(ValueError, match="model did not return valid steps JSON"):
        parse_steps('{"steps": [{"start_s": 1.0, "end_s": 2.0}]}')


def test_compare_steps_exact_match():
    steps = [
        {"title": "A", "start_s": 1.0, "end_s": 3.0},
        {"title": "B", "start_s": 4.0, "end_s": 6.0},
    ]
    result = compare_steps(steps, steps)
    assert result["expected"] == 2
    assert result["found"] == 2
    assert result["hits"] == 2
    assert all(row["hit"] for row in result["rows"])


def test_compare_steps_missing_expected_row():
    found = [
        {"title": "A", "start_s": 1.0, "end_s": 3.0},
        {"title": "B", "start_s": 4.0, "end_s": 6.0},
        {"title": "C", "start_s": 7.0, "end_s": 9.0},
    ]
    expected = found + [{"title": "D", "start_s": 10.0, "end_s": 12.0}]
    result = compare_steps(found, expected)
    assert result["expected"] == 4
    assert result["found"] == 3
    assert result["hits"] == 3
    last = result["rows"][-1]
    assert last["hit"] is False
    assert last["start_error_s"] is None
    assert last["end_error_s"] is None


def test_compare_steps_outside_tolerance():
    found = [{"title": "A", "start_s": 1.0, "end_s": 3.0}]
    expected = [{"title": "A", "start_s": 3.5, "end_s": 3.2}]
    result = compare_steps(found, expected)
    assert result["hits"] == 0
    assert result["rows"][0]["hit"] is False


def test_compare_steps_within_tolerance():
    found = [{"title": "A", "start_s": 1.5, "end_s": 4.0}]
    expected = [{"title": "A", "start_s": 1.0, "end_s": 3.0}]
    result = compare_steps(found, expected)
    assert result["hits"] == 1
    assert result["rows"][0]["hit"] is True


def test_main_no_args(capsys):
    assert main([]) == 2
    assert "Usage" in capsys.readouterr().out


def test_main_missing_video(capsys):
    assert main(["missing.mp4"]) == 1
    assert "missing.mp4" in capsys.readouterr().out
