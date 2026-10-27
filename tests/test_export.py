"""Export a guide as Markdown (task 039). Meta is never called here."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.export import guide_markdown, slugify
from app.jobs import create_job
from app.main import app
from app.routes.upload import settings_dep
from app.schemas import (
    Box,
    Claim,
    Guide,
    Identity,
    Proof,
    ReassemblyStep,
    Safety,
    ScrewMap,
    Step,
    StepProof,
)

PRO_ONLY_STEP = (
    "A qualified professional must do this step. FixScribe does not give instructions for it."
)


@pytest.fixture()
def jobs_tmp(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    app.dependency_overrides[settings_dep] = lambda: Settings(model_api_key="", data_dir=data_dir)
    yield data_dir / "jobs"
    app.dependency_overrides.pop(settings_dep, None)


def _step(index=1, start=12.0, end=31.0, **overrides) -> Step:
    data = {
        "index": index,
        "title": "Remove the back cover",
        "instruction": "Unscrew the four screws and lift the cover.",
        "start_s": start,
        "end_s": end,
        "action": "unscrew",
        "screws": ScrewMap(
            count=4,
            boxes=[
                Box(number=1, x=0.1, y=0.1, w=0.1, h=0.1),
                Box(number=2, x=0.3, y=0.1, w=0.1, h=0.1),
                Box(number=3, x=0.5, y=0.1, w=0.1, h=0.1),
                Box(number=4, x=0.7, y=0.1, w=0.1, h=0.1),
            ],
        ),
        "warnings": ["Keep the screws in order."],
    }
    data.update(overrides)
    return Step(**data)


def _guide(**overrides) -> Guide:
    data = {
        "title": "Replace the Battery!",
        "device": "Phone X",
        "summary": "Open the phone and swap the battery.",
        "difficulty": "medium",
        "estimated_minutes": 25,
        "mode": "narrated",
        "language": "en",
        "tools": ["Phillips screwdriver", "Spudger"],
        "parts": ["Battery"],
        "steps": [_step()],
        "reassembly": [
            ReassemblyStep(
                index=1,
                source_step=1,
                action="Screw in",
                instruction="Put the cover back and tighten the screws.",
            )
        ],
        "checks": ["Every screw goes back."],
        "identity": Identity(
            object_name="Phone X",
            category="electronics",
            task="repair",
        ),
        "safety": Safety(level="normal"),
        "proof": Proof(
            steps=[
                StepProof(
                    index=1,
                    claims=[
                        Claim(field="instruction", status="verified", sources=["video"]),
                        Claim(field="part", status="verified", sources=["video"]),
                        Claim(field="boundaries", status="supported", sources=["audio"]),
                        Claim(field="fastener_count", status="unverified"),
                    ],
                )
            ]
        ),
    }
    data.update(overrides)
    return Guide(**data)


def _write_guide(jobs_dir, guide: Guide) -> str:
    status = create_job(jobs_dir)
    (jobs_dir / status.job_id / "guide.json").write_text(guide.model_dump_json())
    return status.job_id


def test_normal_guide_sections():
    text = guide_markdown(_guide(), "job123")
    assert text.startswith("# Replace the Battery!\n")
    assert "Phone X (electronics) · medium · ~25 min · 1 step" in text
    assert "## Before you start" not in text
    assert "## Professional only" not in text
    assert "## Tools" in text and "- Phillips screwdriver" in text
    assert "## Parts" in text and "- Battery" in text
    assert "### 1. Remove the back cover" in text
    assert "Unscrew the four screws and lift the cover." in text
    assert "Fasteners: 4 screws" in text
    assert "> ⚠ Keep the screws in order." in text
    assert "Video: 0:12–0:31" in text
    assert "Proof: 2 verified · 1 supported · 1 unverified" in text
    assert "## Reassembly" in text
    assert "1. Put the cover back and tighten the screws." in text
    assert "## Automatic checks" in text
    assert "- Every screw goes back." in text
    assert text.rstrip().endswith("Muse Voice and SAM 3.1 by Meta.")
    assert "<img" not in text and "</" not in text


def test_empty_sections_are_skipped():
    guide = _guide(tools=[], parts=[], reassembly=[], checks=[], proof=None)
    text = guide_markdown(guide, "job123")
    assert "## Tools" not in text
    assert "## Parts" not in text
    assert "## Reassembly" not in text
    assert "## Automatic checks" not in text
    assert "Proof:" not in text


def test_caution_checklist():
    guide = _guide(
        safety=Safety(
            level="caution",
            reasons=["Mains voltage inside."],
            prechecks=["Unplug the device.", "Let it cool down."],
        )
    )
    text = guide_markdown(guide, "job123")
    assert "## Before you start" in text
    assert "- [ ] Unplug the device." in text
    assert "- [ ] Let it cool down." in text
    assert "Mains voltage inside." in text


def test_professional_only_has_no_instructions():
    guide = _guide(
        safety=Safety(level="professional_only", reasons=["Gas line involved."]),
        steps=[_step(instruction=PRO_ONLY_STEP)],
        reassembly=[],
    )
    text = guide_markdown(guide, "job123")
    assert "## Professional only" in text
    assert "Gas line involved." in text
    assert "Turn the gas valve" not in text
    assert PRO_ONLY_STEP in text
    assert "## Reassembly" not in text


def test_plural_kinds():
    bolts = _guide(steps=[_step(screws=ScrewMap(count=2, kind="bolt"))])
    assert "Fasteners: 2 bolts" in guide_markdown(bolts, "job123")
    glasses = _guide(steps=[_step(screws=ScrewMap(count=2, kind="glass"))])
    assert "Fasteners: 2 glasses" in guide_markdown(glasses, "job123")
    single = _guide(steps=[_step(screws=ScrewMap(count=1, kind="screw"))])
    assert "Fasteners: 1 screw" in guide_markdown(single, "job123")
    none = _guide(steps=[_step(screws=None)])
    assert "Fasteners:" not in guide_markdown(none, "job123")


def test_mmss_times():
    guide = _guide(steps=[_step(start=0.0, end=75.0)])
    assert "Video: 0:00–1:15" in guide_markdown(guide, "job123")


def test_slugify():
    assert slugify("Replace the Battery!") == "replace-the-battery"
    assert slugify("  Washing   machine / drum ") == "washing-machine-drum"
    assert len(slugify("x" * 100)) == 60
    assert slugify("!!!") == "guide"


def test_route_200_with_headers(jobs_tmp):
    job_id = _write_guide(jobs_tmp, _guide())
    response = TestClient(app).get(f"/guides/{job_id}/export.md")
    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    disposition = response.headers["content-disposition"]
    assert disposition == 'attachment; filename="replace-the-battery.md"'
    assert response.text.startswith("# Replace the Battery!")


def test_route_404(jobs_tmp):
    client = TestClient(app)
    assert client.get("/guides/nothere/export.md").status_code == 404
    status = create_job(jobs_tmp)  # a job without a guide yet
    assert client.get(f"/guides/{status.job_id}/export.md").status_code == 404


def test_general_warnings_are_exported_once():
    from app.export import guide_markdown
    from app.schemas import Guide, Safety

    guide = Guide(
        title="t",
        device="d",
        mode="silent",
        warnings=["Unplug it.", "A charged battery can catch fire."],
        safety=Safety(level="caution", prechecks=["Unplug it."]),
    )
    text = guide_markdown(guide, "abc")
    assert "> ⚠ A charged battery can catch fire." in text
    assert text.count("Unplug it.") == 1
