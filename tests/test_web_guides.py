"""Guide page and media routes (task 010). Meta is never called here."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.jobs import create_job
from app.main import app
from app.routes.upload import settings_dep
from app.schemas import Box, Guide, ReassemblyStep, ScrewMap, Step


@pytest.fixture()
def jobs_tmp(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    app.dependency_overrides[settings_dep] = lambda: Settings(model_api_key="", data_dir=data_dir)
    yield data_dir / "jobs"
    app.dependency_overrides.pop(settings_dep, None)


def _guide(**overrides) -> Guide:
    data = {
        "title": "Replace the battery",
        "device": "Phone X",
        "summary": "Open the phone and swap the battery.",
        "difficulty": "medium",
        "estimated_minutes": 25,
        "mode": "narrated",
        "language": "en",
        "tools": ["Phillips screwdriver", "Spudger"],
        "warnings": ["Disconnect the battery before touching the board."],
        "steps": [
            Step(
                index=1,
                title="Remove the back cover",
                instruction="Unscrew the four screws and lift the cover.",
                start_s=0.0,
                end_s=12.0,
                action="unscrew",
                screws=ScrewMap(
                    count=4,
                    boxes=[
                        Box(number=1, x=0.1, y=0.1, w=0.1, h=0.1),
                        Box(number=2, x=0.3, y=0.1, w=0.1, h=0.1),
                        Box(number=3, x=0.5, y=0.1, w=0.1, h=0.1),
                        Box(number=4, x=0.7, y=0.1, w=0.1, h=0.1),
                    ],
                ),
                clip="steps/01.mp4",
                image="steps/01.jpg",
                warnings=["Keep the screws in order."],
            )
        ],
        "reassembly": [
            ReassemblyStep(
                index=1,
                source_step=1,
                action="Screw in",
                instruction="Put the cover back and tighten the screws.",
                parts=["back cover"],
                screws=ScrewMap(
                    count=4,
                    boxes=[
                        Box(number=1, x=0.1, y=0.1, w=0.1, h=0.1),
                        Box(number=2, x=0.3, y=0.1, w=0.1, h=0.1),
                        Box(number=3, x=0.5, y=0.1, w=0.1, h=0.1),
                        Box(number=4, x=0.7, y=0.1, w=0.1, h=0.1),
                    ],
                ),
            )
        ],
        "checks": [],
    }
    data.update(overrides)
    return Guide(**data)


def _write_guide(jobs_dir, guide: Guide) -> str:
    status = create_job(jobs_dir)
    folder = jobs_dir / status.job_id
    (folder / "guide.json").write_text(guide.model_dump_json())
    steps_dir = folder / "steps"
    steps_dir.mkdir(exist_ok=True)
    (steps_dir / "01.jpg").write_bytes(b"fake-jpeg")
    (steps_dir / "01.mp4").write_bytes(b"fake-clip")
    (folder / "video.mp4").write_bytes(b"fake-video")
    return status.job_id


def test_guide_page_renders(jobs_tmp):
    job_id = _write_guide(jobs_tmp, _guide())
    response = TestClient(app).get(f"/guides/{job_id}")
    assert response.status_code == 200
    assert "Replace the battery" in response.text
    assert "Take apart" in response.text
    assert "Put back" in response.text
    assert "Watch in video" in response.text
    assert 'data-start="' in response.text
    assert f"/media/{job_id}/steps/01.mp4" in response.text
    assert "Keep the screws in order." in response.text


def test_screw_check_amber_and_green(jobs_tmp):
    job_id = _write_guide(jobs_tmp, _guide(checks=["Screw check: 6 screws removed, 4 put back."]))
    response = TestClient(app).get(f"/guides/{job_id}")
    assert response.status_code == 200
    assert "Screw check: 6 screws removed, 4 put back." in response.text

    ok_id = _write_guide(jobs_tmp, _guide(checks=[]))
    ok_response = TestClient(app).get(f"/guides/{ok_id}")
    assert ok_response.status_code == 200
    assert "Every screw goes back" in ok_response.text


def test_needs_review_badge(jobs_tmp):
    guide = _guide()
    guide.steps[0].review = "needs_review"
    job_id = _write_guide(jobs_tmp, guide)
    response = TestClient(app).get(f"/guides/{job_id}")
    assert response.status_code == 200
    assert "Check this step" in response.text


def test_guide_not_ready_and_bad_id(jobs_tmp):
    status = create_job(jobs_tmp)
    response = TestClient(app).get(f"/guides/{status.job_id}")
    assert response.status_code == 404
    assert "not ready" in response.text
    assert f"/jobs/{status.job_id}" in response.text

    bad = TestClient(app).get("/guides/nothere")
    assert bad.status_code == 404
    assert "not ready" in bad.text


def test_media_routes(jobs_tmp):
    job_id = _write_guide(jobs_tmp, _guide())
    client = TestClient(app)
    assert client.get(f"/media/{job_id}/steps/01.jpg").status_code == 200
    assert client.get(f"/media/{job_id}/video.mp4").status_code == 200
    assert client.get(f"/media/{job_id}/guide.json").status_code == 404
    assert client.get(f"/media/{job_id}/../status.json").status_code == 404
    assert client.get(f"/media/{job_id}/steps/99.jpg").status_code == 404
    assert client.get("/media/nothere/steps/01.jpg").status_code == 404


def test_overlay_images_match_the_media_rule():
    from app.routes.guides import _MEDIA_RE

    assert _MEDIA_RE.fullmatch("steps/03_overlay.jpg")
    assert _MEDIA_RE.fullmatch("steps/03.mp4") and _MEDIA_RE.fullmatch("video.mp4")
    assert not _MEDIA_RE.fullmatch("steps/03_overlay.mp4")
    assert not _MEDIA_RE.fullmatch("../guide.json")


def test_guide_page_has_3d_views_proof_and_repair_mode(tmp_path):
    from app.routes.guides import step_views
    from app.schemas import Box, Claim, Proof, ScrewMap, StepProof

    guide = _guide()
    step = guide.steps[0]
    guide.steps[0] = step.model_copy(
        update={
            "image": "steps/01.jpg",
            "screws": ScrewMap(
                count=2, kind="bolt", boxes=[Box(number=1, x=0.1, y=0.2, w=0.1, h=0.1)]
            ),
        }
    )
    guide.proof = Proof(
        steps=[StepProof(index=1, claims=[Claim(field="part", status="verified", sources=["SAM"])])]
    )
    parts = {1: {"label": "back cover", "x": 10.0, "y": 20.0, "w": 50.0, "h": 40.0}}
    view = step_views(guide, "abc", parts)[0]
    assert view["fasteners"] == "2 bolts"
    assert view["pins"] == [{"n": 1, "x": 15.0, "y": 25.0}]
    assert view["part"]["label"] == "back cover"
    assert view["claims"][0] == {"label": "Which part", "status": "verified", "sources": ["SAM"]}
    assert view["checkable"] is True
    assert view["image"] == "/media/abc/steps/01.jpg"


def test_guide_page_renders_repair_mode_and_export(jobs_tmp):
    job_id = _write_guide(jobs_tmp, _guide())
    text = TestClient(app).get(f"/guides/{job_id}").text
    assert 'id="repair"' in text and "Start repair" in text
    assert f"/guides/{job_id}/export.md" in text
    assert f"/guides/{job_id}/tray" in text
