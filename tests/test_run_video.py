from scripts.run_video import main


def test_usage_and_missing_inputs(tmp_path, monkeypatch):
    assert main([]) == 2
    assert main([str(tmp_path / "missing.mp4")]) == 1
    video = tmp_path / "x.mp4"
    video.write_bytes(b"0")
    monkeypatch.setenv("MODEL_API_KEY", "")  # .env does not override it
    assert main([str(video)]) == 1  # no key: stops before any Meta call
