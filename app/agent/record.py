"""The agent's case file: what it has proven so far, and one line per turn.

Everything lives in ``<job>/agent/``:

- ``record.json``  the case record (status, parts catalog, steps, open question, sign-off)
- ``turns.jsonl``  one line per turn: plan (model decision), act (tool call), observe (result)
- ``frames/``, ``crops/``  images the agent looked at, referenced by relative path
- ``answer.json``  the person's answer to an open question (written by the console)
- ``signoff.json`` the person's approval or rejection of the finished guide

Boxes are always on a 0..1000 grid of the frame they belong to: [x_min, y_min, x_max, y_max].
The agent never writes these files directly: its tools do, after their checks pass.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app import artifacts

Status = Literal["idle", "running", "needs_input", "awaiting_signoff", "done", "paused", "failed"]
Box = tuple[int, int, int, int]


class Part(BaseModel):
    id: str  # "A", "B", ... like a furniture manual
    name: str  # short common name: "metal bolt", "side panel"
    count: int = 1
    frame: str = ""  # relative path of the frame where it was proven, e.g. "frames/t012.4.jpg"
    t_s: float = 0.0
    box: Box | None = None
    crop: str = ""  # relative path of the cut-out, e.g. "crops/A.png"
    verified: bool = False
    evidence: list[str] = Field(default_factory=list)  # one short line per passed check


class AgentStep(BaseModel):
    n: int
    action: str
    text: str
    parts: list[str] = Field(default_factory=list)  # part ids used in this step
    start_s: float = 0.0
    end_s: float = 0.0
    frame: str = ""  # the frame that shows the step done
    to_box: Box | None = None  # where the parts end up, on that frame
    quote: str = ""  # the technician's own words for this step, checked against the transcript
    verified: bool = False
    evidence: list[str] = Field(default_factory=list)


class Question(BaseModel):
    text: str
    frame: str = ""
    box: Box | None = None
    options: list[str] = Field(default_factory=list)


class SignOff(BaseModel):
    approved: bool
    notes: str = ""


class AgentRecord(BaseModel):
    status: Status = "idle"
    objective: str = ""
    turn: int = 0
    max_turns: int = 30
    usd: float = 0.0
    parts: list[Part] = Field(default_factory=list)
    steps: list[AgentStep] = Field(default_factory=list)
    question: Question | None = None
    signoff: SignOff | None = None
    notes: list[str] = Field(default_factory=list)  # refusals and problems, newest last


class Act(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)


class Observe(BaseModel):
    ok: bool
    text: str
    image: str = ""  # relative path inside agent/, when the tool produced an image


class Turn(BaseModel):
    turn: int
    plan: str = ""  # the model's short reason for this action
    tokens: int = 0
    usd: float = 0.0
    act: Act | None = None
    observe: Observe | None = None


def agent_dir(job_dir: Path) -> Path:
    return Path(job_dir) / "agent"


def load_record(job_dir: Path) -> AgentRecord:
    """The record, or an empty idle one when the agent never ran."""
    path = agent_dir(job_dir) / "record.json"
    if not path.exists():
        return AgentRecord()
    return AgentRecord.model_validate_json(path.read_text(encoding="utf-8"))


def save_record(job_dir: Path, record: AgentRecord) -> None:
    artifacts.write_text_atomic(
        agent_dir(job_dir) / "record.json", record.model_dump_json(indent=2)
    )


def append_turn(job_dir: Path, turn: Turn) -> None:
    """Add one turn line. Only the agent loop writes turns, one process per job."""
    path = agent_dir(job_dir) / "turns.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(turn.model_dump_json() + "\n")


def load_turns(job_dir: Path, after: int = 0) -> list[Turn]:
    """Turns with a number above ``after``; a half-written last line is skipped."""
    path = agent_dir(job_dir) / "turns.jsonl"
    if not path.exists():
        return []
    turns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            turn = Turn.model_validate_json(line)
        except ValueError:
            continue
        if turn.turn > after:
            turns.append(turn)
    return turns


def write_answer(job_dir: Path, answer: str) -> None:
    artifacts.write_json_atomic(agent_dir(job_dir) / "answer.json", {"answer": answer})


def take_answer(job_dir: Path) -> str | None:
    """The person's answer, removed once read so it is used exactly once."""
    path = agent_dir(job_dir) / "answer.json"
    if not path.exists():
        return None
    answer = str(json.loads(path.read_text(encoding="utf-8")).get("answer", ""))
    path.unlink()
    return answer


def write_signoff(job_dir: Path, signoff: SignOff) -> None:
    artifacts.write_text_atomic(agent_dir(job_dir) / "signoff.json", signoff.model_dump_json())
