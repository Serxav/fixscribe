"""Printable fastener tray page (task 030). Meta is never called here."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.jobs import create_job
from app.main import app
from app.routes.upload import settings_dep
from app.schemas import Box, Guide, Identity, ReassemblyStep, Safety, ScrewMap, Step
from app.tray import reassembly_lines, tray_cells


@pytest.fixture()
def jobs_tmp(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    app.dependency_overrides[settings_dep] = lambda: Settings(model_api_key="", data_dir=data_dir)
    yield data_dir / "jobs"
    app.dependency_overrides.pop(settings_dep, None)


def _step(index, title, screws=None, **overrides):
    data = {
        "index": index,
        "title": title,
        "instruction": f"Do step {index}.",
        "start_s": float((index - 1) * 10),
        "end_s": float(index * 10),
    }
    if screws is not None:
        data["screws"] = screws
    data.update(overrides)
    return Step(**data)


def _guide(**overrides):
    data = {
        "title": "Replace the fan",
        "device": "Laptop Y",
        "mode": "narrated",
        "steps": [
            _step(
                1,
                "Remove the back screws",
                screws=ScrewMap(
                    count=4,
                    boxes=[
                        Box(number=1, x=0.1, y=0.1, w=0.1, h=0.1),
                        Box(number=2, x=0.3, y=0.1, w=0.1, h=0.1),
                        Box(number=3, x=0.5, y=0.1, w=0.1, h=0.1),
                        Box(number=4, x=0.7, y=0.1, w=0.1, h=0.1),
                    ],
                ),
                overlay="steps/01_overlay.jpg",
            ),
            _step(2, "Lift the cover"),
            _step(
                3,
                "Unbolt the fan",
                screws=ScrewMap(count=2, kind="bolt"),
                image="steps/03.jpg",
            ),
        ],
        "reassembly": [
            ReassemblyStep(
                index=1,
                source_step=3,
                action="Bolt on",
                instruction="Put the fan back and tighten the bolts.",
            ),
            ReassemblyStep(
                index=2,
                source_step=1,
                action="Screw in",
                instruction="Put the cover back and tighten the screws.",
            ),
        ],
        "identity": Identity(
            object_name="Laptop Y",
            category="electronics",
            task="repair",
        ),
    }
    data.update(overrides)
    return Guide(**data)


def _write_guide(jobs_dir, guide: Guide) -> str:
    status = create_job(jobs_dir)
    (jobs_dir / status.job_id / "guide.json").write_text(guide.model_dump_json())
    return status.job_id


def test_numbers_from_boxes():
    cells = tray_cells(_guide())
    assert [cell.step for cell in cells] == [1, 3]
    assert cells[0].numbers == [1, 2, 3, 4]


def test_numbers_from_count_without_boxes():
    cells = tray_cells(_guide())
    assert cells[1].numbers == [1, 2]
    assert cells[1].count == 2
    assert cells[1].kind == "bolt"


def test_steps_without_fasteners_have_no_cell():
    cells = tray_cells(_guide())
    assert len(cells) == 2
    assert all(cell.count > 0 for cell in cells)


def test_image_prefers_overlay_over_image():
    cells = tray_cells(_guide())
    assert cells[0].image == "steps/01_overlay.jpg"
    assert cells[1].image == "steps/03.jpg"


def test_empty_guide_has_no_cells_or_lines():
    guide = _guide(steps=[_step(1, "Look at it")], reassembly=[])
    assert tray_cells(guide) == []
    assert reassembly_lines(guide) == []


def test_reassembly_lines_point_to_cells():
    lines = reassembly_lines(_guide())
    assert lines == [
        "1. Put the fan back and tighten the bolts. (tray cell 3)",
        "2. Put the cover back and tighten the screws. (tray cell 1)",
    ]


def test_route_renders_titles_and_page_css(jobs_tmp):
    job_id = _write_guide(jobs_tmp, _guide())
    response = TestClient(app).get(f"/guides/{job_id}/tray")
    assert response.status_code == 200
    assert "Remove the back screws" in response.text
    assert "Unbolt the fan" in response.text
    assert "Laptop Y" in response.text
    assert "@page" in response.text
    assert "2 bolts" in response.text
    assert "4 screws" in response.text
    assert "(tray cell 3)" in response.text
    assert "FixScribe — keep each fastener in its cell." in response.text


def test_route_without_fasteners_says_so(jobs_tmp):
    guide = _guide(steps=[_step(1, "Look at it")], reassembly=[])
    job_id = _write_guide(jobs_tmp, guide)
    response = TestClient(app).get(f"/guides/{job_id}/tray")
    assert response.status_code == 200
    assert "no fasteners" in response.text


def test_professional_only_shows_no_tray(jobs_tmp):
    guide = _guide(safety=Safety(level="professional_only", reasons=["gas"]))
    job_id = _write_guide(jobs_tmp, guide)
    response = TestClient(app).get(f"/guides/{job_id}/tray")
    assert response.status_code == 200
    assert "This job is for a qualified professional. No tray." in response.text
    assert "Remove the back screws" not in response.text


def test_bad_id_and_missing_guide_are_404(jobs_tmp):
    assert TestClient(app).get("/guides/nothere/tray").status_code == 404
    status = create_job(jobs_tmp)
    assert TestClient(app).get(f"/guides/{status.job_id}/tray").status_code == 404
