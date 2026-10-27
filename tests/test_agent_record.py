from app.agent import record
from app.agent.record import Act, AgentRecord, Observe, Part, SignOff, Turn


def test_empty_job_gives_idle_record(tmp_path):
    assert record.load_record(tmp_path).status == "idle"
    assert record.load_turns(tmp_path) == []
    assert record.take_answer(tmp_path) is None


def test_record_round_trip(tmp_path):
    rec = AgentRecord(status="running", objective="Build the table")
    rec.parts.append(Part(id="A", name="metal bolt", count=4, box=(10, 20, 30, 40), verified=True))
    record.save_record(tmp_path, rec)
    again = record.load_record(tmp_path)
    assert again.parts[0].box == (10, 20, 30, 40)
    assert again.status == "running"


def test_turns_append_and_filter(tmp_path):
    for n in (1, 2, 3):
        record.append_turn(
            tmp_path,
            Turn(
                turn=n,
                plan="look",
                act=Act(tool="look", args={"t_s": n}),
                observe=Observe(ok=True, text="ok"),
            ),
        )
    assert [t.turn for t in record.load_turns(tmp_path, after=1)] == [2, 3]


def test_half_written_turn_line_is_skipped(tmp_path):
    record.append_turn(tmp_path, Turn(turn=1))
    with (record.agent_dir(tmp_path) / "turns.jsonl").open("a") as fh:
        fh.write('{"turn": 2, "pl')
    assert [t.turn for t in record.load_turns(tmp_path)] == [1]


def test_answer_is_used_once(tmp_path):
    record.write_answer(tmp_path, "yes")
    assert record.take_answer(tmp_path) == "yes"
    assert record.take_answer(tmp_path) is None


def test_signoff_written(tmp_path):
    record.write_signoff(tmp_path, SignOff(approved=False, notes="step 3 is wrong"))
    assert "step 3" in (record.agent_dir(tmp_path) / "signoff.json").read_text()
