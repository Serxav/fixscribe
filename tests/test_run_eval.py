import json

from app import artifacts
from app.jobs import create_job, update_status
from app.schemas import Guide, Manifest, ScrewMap, StageRecord, Step
from eval.run_eval import format_table, labelled_videos, main, run_eval

EXPECTED = {
    "steps": [
        {"title": "Remove cover", "start_s": 0.0, "end_s": 10.0, "screws": 2},
        {"title": "Disconnect battery", "start_s": 10.0, "end_s": 20.0},
    ]
}


def finished_job(jobs_dir, *, located=2):
    job_id = create_job(jobs_dir).job_id
    folder = jobs_dir / job_id
    from app.schemas import Box

    boxes = [Box(number=n, x=0.1 * n, y=0.1, w=0.05, h=0.05) for n in range(1, located + 1)]
    guide = Guide(
        title="t",
        device="d",
        mode="narrated",
        duration_s=20.0,
        steps=[
            Step(index=1, title="a", instruction="a", start_s=0.5, end_s=10.0,
                 screws=ScrewMap(count=2, boxes=boxes)),
            Step(index=2, title="b", instruction="b", start_s=10.0, end_s=19.0),
        ],
    )  # fmt: skip
    artifacts.save(folder, guide)
    record = StageRecord(status="done", version="2", started_at="x", seconds=3.0, usd=0.05)
    artifacts.save(folder, Manifest(stages={"analyze": record}, total_seconds=3.0, total_usd=0.05))
    update_status(job_id, jobs_dir, state="done")
    return folder


def samples_dir(tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "repair.mp4").write_bytes(b"0")
    (samples / "repair.expected.json").write_text(json.dumps(EXPECTED))
    (samples / "unlabelled.mp4").write_bytes(b"0")
    return samples


def test_only_labelled_videos_are_used(tmp_path):
    assert [v.name for v, _ in labelled_videos(samples_dir(tmp_path))] == ["repair.mp4"]


def test_scores_quality_time_and_money(tmp_path):
    samples = samples_dir(tmp_path)
    jobs = tmp_path / "jobs"
    result = run_eval(samples, jobs, label="t", process=lambda video: finished_job(jobs))
    row = result["videos"][0]
    assert row["state"] == "done"
    assert row["step_f1"] == 1.0
    assert row["boundary_hit_rate"] == 1.0
    assert (row["screws_located_by_sam"], row["screws_labelled"]) == (2, 2)
    assert (row["seconds"], row["usd"]) == (3.0, 0.05)
    assert row["stages"]["analyze"]["usd"] == 0.05
    assert result["summary"]["usd"] == 0.05
    assert "1/1 guides" in format_table(result)


def test_failed_job_is_reported_not_crashed(tmp_path):
    samples = samples_dir(tmp_path)
    jobs = tmp_path / "jobs"

    def failing(video):
        job_id = create_job(jobs).job_id
        update_status(job_id, jobs, state="failed", error="analyze failed: Spark returned nothing")
        return jobs / job_id

    result = run_eval(samples, jobs, label="t", process=failing)
    assert result["videos"][0]["error"].startswith("analyze failed")
    assert result["summary"]["guides"] == 0


def test_cli_refuses_to_spend_without_confirmation(tmp_path, capsys):
    samples = samples_dir(tmp_path)
    assert main(["--samples", str(samples)]) == 2
    assert "--confirm-spend" in capsys.readouterr().out
    assert main(["--samples", str(tmp_path / "nothing")]) == 1
