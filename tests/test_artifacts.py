import pytest

from app.artifacts import ArtifactError, exists, load, load_optional, save
from app.schemas import IngestInfo, Manifest, StageRecord, Transcript, Turn


def test_save_and_load_round_trip(tmp_path):
    info = IngestInfo(duration_s=12.5, width=720, height=1280, has_audio=True)
    path = save(tmp_path, info)
    assert path.name == "ingest.json"
    assert load(tmp_path, IngestInfo) == info
    assert [p.name for p in tmp_path.iterdir()] == ["ingest.json"]  # no temp files left


def test_missing_and_optional(tmp_path):
    with pytest.raises(ArtifactError, match="missing transcript.json"):
        load(tmp_path, Transcript)
    assert load_optional(tmp_path, Transcript) is None
    assert not exists(tmp_path, Transcript)


def test_broken_file_names_the_field(tmp_path):
    (tmp_path / "transcript.json").write_text('{"mode": "narrated", "turns": [{"start_s": -1}]}')
    with pytest.raises(ArtifactError, match=r"broken transcript.json: turns\.0\.start_s"):
        load(tmp_path, Transcript)


def test_not_json_is_broken(tmp_path):
    (tmp_path / "ingest.json").write_text("{")
    with pytest.raises(ArtifactError, match="broken ingest.json"):
        load(tmp_path, IngestInfo)


def test_unknown_fields_are_rejected(tmp_path):
    (tmp_path / "ingest.json").write_text(
        '{"duration_s": 1, "width": 1, "height": 1, "has_audio": false, "colour": "red"}'
    )
    with pytest.raises(ArtifactError, match="colour"):
        load(tmp_path, IngestInfo)


def test_manifest_model(tmp_path):
    record = StageRecord(
        status="done", version="1", started_at="2026-10-26T00:00:00+00:00", seconds=1.5
    )
    save(tmp_path, Manifest(stages={"ingest": record}, total_seconds=1.5))
    assert load(tmp_path, Manifest).stages["ingest"].seconds == 1.5
    assert (
        Transcript(mode="silent", turns=[Turn(start_s=0, end_s=1, text="hi")]).turns[0].text == "hi"
    )
