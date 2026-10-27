"""Agent Console page and API: watch the agent, answer it, sign off. No network."""

import json

import pytest
from fastapi.testclient import TestClient

from app.agent import loop
from app.agent import record as record_mod
from app.agent.record import Act, AgentRecord, Observe, Turn
from app.config import Settings
from app.jobs import create_job
from app.main import ROOT, app
from app.routes.upload import settings_dep


@pytest.fixture()
def jobs_dir(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    app.dependency_overrides[settings_dep] = lambda: Settings(data_dir=data_dir)
    yield data_dir / "jobs"
    app.dependency_overrides.pop(settings_dep, None)


def _job(jobs_dir, **overrides):
    status = create_job(jobs_dir)
    folder = jobs_dir / status.job_id
    record = AgentRecord(**({"status": "idle"} | overrides))
    record_mod.save_record(folder, record)
    return status.job_id, folder


def _turn(n, tool="look", ok=True):
    return Turn(
        turn=n,
        plan=f"plan {n}",
        tokens=10 * n,
        act=Act(tool=tool, args={"t_s": n}),
        observe=Observe(ok=ok, text=f"saw {n}"),
    )


def test_console_page_200_and_404(jobs_dir):
    job_id, _ = _job(jobs_dir)
    client = TestClient(app)

    response = client.get(f"/jobs/{job_id}/console")
    assert response.status_code == 200
    assert "Agent console" in response.text
    assert "/static/console.js" in response.text

    assert client.get("/jobs/nothere/console").status_code == 404
    assert client.get("/jobs/abcdef123456/console").status_code == 404


def test_agent_api_returns_record_and_filtered_turns(jobs_dir):
    job_id, folder = _job(jobs_dir, status="running", turn=3, usd=0.12)
    for n in (1, 2, 3):
        record_mod.append_turn(folder, _turn(n))

    client = TestClient(app)
    body = client.get(f"/api/jobs/{job_id}/agent").json()
    assert body["record"]["status"] == "running"
    assert body["record"]["usd"] == 0.12
    assert [t["turn"] for t in body["turns"]] == [1, 2, 3]

    body = client.get(f"/api/jobs/{job_id}/agent?after=2").json()
    assert [t["turn"] for t in body["turns"]] == [3]

    assert client.get("/api/jobs/nothere/agent").status_code == 404


def test_start_and_resume_call_launch(jobs_dir, monkeypatch):
    job_id, folder = _job(jobs_dir)
    calls = []

    def fake_launch(job_dir, *, resume=False):
        calls.append((str(job_dir), resume))
        return True

    monkeypatch.setattr(loop, "launch", fake_launch)
    client = TestClient(app)

    response = client.post(f"/api/jobs/{job_id}/agent/start")
    assert response.status_code == 200
    assert response.json() == {"started": True}

    response = client.post(f"/api/jobs/{job_id}/agent/resume")
    assert response.status_code == 200
    assert response.json() == {"started": True}

    assert calls == [(str(folder), False), (str(folder), True)]


def test_start_not_implemented_is_501(jobs_dir, monkeypatch):
    job_id, _ = _job(jobs_dir)

    def boom(job_dir, *, resume=False):
        raise NotImplementedError("the agent loop is being built")

    monkeypatch.setattr(loop, "launch", boom)
    client = TestClient(app)

    for path in ("start", "resume"):
        response = client.post(f"/api/jobs/{job_id}/agent/{path}")
        assert response.status_code == 501
        assert response.json() == {"error": "The agent is not ready yet."}


def test_answer_flow(jobs_dir, monkeypatch):
    monkeypatch.setattr(loop, "launch", lambda job_dir, *, resume=True: True)
    job_id, folder = _job(jobs_dir, status="running")
    client = TestClient(app)

    response = client.post(f"/api/jobs/{job_id}/agent/answer", json={"answer": "yes"})
    assert response.status_code == 409

    record_mod.save_record(folder, AgentRecord(status="needs_input"))
    assert client.post(f"/api/jobs/{job_id}/agent/answer", json={"answer": ""}).status_code == 400
    blank = client.post(f"/api/jobs/{job_id}/agent/answer", json={"answer": "   "})
    assert blank.status_code == 400
    assert client.post(f"/api/jobs/{job_id}/agent/answer", json={}).status_code == 400
    assert (
        client.post(f"/api/jobs/{job_id}/agent/answer", json={"answer": "x" * 501}).status_code
        == 400
    )

    response = client.post(f"/api/jobs/{job_id}/agent/answer", json={"answer": "the left bolt"})
    assert response.status_code == 200
    stored = json.loads((folder / "agent" / "answer.json").read_text(encoding="utf-8"))
    assert stored == {"answer": "the left bolt"}


def test_signoff_flow(jobs_dir, monkeypatch):
    monkeypatch.setattr(loop, "launch", lambda job_dir, *, resume=True: True)
    job_id, folder = _job(jobs_dir, status="running")
    client = TestClient(app)

    response = client.post(
        f"/api/jobs/{job_id}/agent/signoff", json={"approved": True, "notes": ""}
    )
    assert response.status_code == 409

    record_mod.save_record(folder, AgentRecord(status="awaiting_signoff"))
    reject = {"approved": False, "notes": ""}
    assert client.post(f"/api/jobs/{job_id}/agent/signoff", json=reject).status_code == 400
    reject_blank = {"approved": False, "notes": "   "}
    assert client.post(f"/api/jobs/{job_id}/agent/signoff", json=reject_blank).status_code == 400

    response = client.post(
        f"/api/jobs/{job_id}/agent/signoff",
        json={"approved": False, "notes": "step 2 is wrong"},
    )
    assert response.status_code == 200
    stored = json.loads((folder / "agent" / "signoff.json").read_text(encoding="utf-8"))
    assert stored == {"approved": False, "notes": "step 2 is wrong"}

    record_mod.save_record(folder, AgentRecord(status="awaiting_signoff"))
    response = client.post(
        f"/api/jobs/{job_id}/agent/signoff", json={"approved": True, "notes": ""}
    )
    assert response.status_code == 200


def test_media_serves_frames_and_blocks_traversal(jobs_dir):
    job_id, folder = _job(jobs_dir)
    frames = folder / "agent" / "frames"
    frames.mkdir(parents=True)
    (frames / "t1.jpg").write_bytes(b"\xff\xd8\xff fake jpeg")
    client = TestClient(app)

    response = client.get(f"/jobs/{job_id}/agent/media/frames/t1.jpg")
    assert response.status_code == 200

    assert client.get(f"/jobs/{job_id}/agent/media/frames/missing.jpg").status_code == 404
    assert client.get(f"/jobs/{job_id}/agent/media/../record.json").status_code == 404
    assert client.get(f"/jobs/{job_id}/agent/media/frames/../../x.jpg").status_code == 404
    assert client.get(f"/jobs/{job_id}/agent/media/frames/t1.txt").status_code == 404


def test_guide_and_job_pages_link_the_console(jobs_dir):
    for name in ("guide.html", "job.html"):
        text = (ROOT / "web" / "templates" / name).read_text(encoding="utf-8")
        assert text.count("Agent console") == 1
        assert "/jobs/{{ job_id }}/console" in text
