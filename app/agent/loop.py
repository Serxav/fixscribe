"""The agent loop: Muse Wonder picks one tool per turn until the guide is filed.

Like a person at a desk: it reads the case file (video, narration, a draft), then works with its
tools, one call per turn. Every turn is saved (``turns.jsonl``) and the record after it
(``record.json``), so the console can watch live and a stopped run can continue. The run stops
when the agent asks the person something (needs_input), files the guide (awaiting_signoff), hits
the turn limit or the budget (paused), or the model call fails (paused). It never loses work.

Background: ``launch``. By hand: ``python -m app.agent.loop <job_dir> [--resume]``.
"""

import base64
import json
import logging
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from app import artifacts
from app.agent import record as rec
from app.agent.record import Act, AgentRecord, Observe, SignOff, Turn
from app.agent.tools import DEFINITIONS, Case, Result, run_tool
from app.config import Settings
from app.meta_client import BudgetExceeded, MetaError, make_client, token_cost
from app.schemas import Analysis, Identity, IngestInfo, Transcript

logger = logging.getLogger(__name__)

PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "agent_v1.md"
MAX_TURNS = 30
MORE_TURNS = 15
MAX_OUTPUT_TOKENS = 16000  # reasoning counts here too
EFFORT = "high"


class AgentAlreadyRunning(Exception):
    pass


# --- the case file ---------------------------------------------------------------------------


def objective(identity: Identity | None, analysis: Analysis | None) -> str:
    name = identity.object_name if identity else (analysis.device if analysis else "the object")
    task = identity.task if identity else "repair"
    verb = {"assemble": "build", "disassemble": "take apart"}.get(task, task)
    return f"Write a verified guide to {verb} the {name}, from this video."


def case_file(job_dir: Path, record: AgentRecord, info: IngestInfo) -> str:
    """The first message: the objective, what is known, the narration and the draft steps."""
    identity = artifacts.load_optional(job_dir, Identity)
    analysis = artifacts.load_optional(job_dir, Analysis)
    transcript = artifacts.load_optional(job_dir, Transcript)
    lines = [f"Objective: {record.objective}", f"Video length: {info.duration_s:.1f} s"]
    if identity:
        lines.append(f"Object: {identity.object_name} ({identity.category}); task: {identity.task}")
    if transcript and transcript.turns:
        lines.append("\nNarration (seconds):")
        lines += [f"[{t.start_s:.1f}-{t.end_s:.1f}] {t.text}" for t in transcript.turns]
    else:
        lines.append('\nThe video has no narration: use quote "".')
    if analysis and analysis.steps:
        lines.append("\nDraft steps from a faster model (check them, they can be wrong):")
        for n, step in enumerate(analysis.steps, start=1):
            part = f" [part: {step.target_part}]" if step.target_part else ""
            lines.append(f"{n}. [{step.start_s:.1f}-{step.end_s:.1f}] {step.title}{part}")
    if record.parts or record.steps:
        lines.append("\nAlready in the record (keep it, continue from here):")
        lines += [f"part {p.id}: {p.name} x{p.count}" for p in record.parts]
        lines += [f"step {s.n}: {s.text}" for s in record.steps]
    return "\n".join(lines)


def load_case(job_dir: Path, client: Any, record: AgentRecord) -> Case:
    info = artifacts.load(job_dir, IngestInfo)
    transcript = artifacts.load_optional(job_dir, Transcript)
    turns = [(t.start_s, t.end_s, t.text) for t in transcript.turns] if transcript else []
    case = Case(
        job_dir=job_dir, client=client, record=record, duration_s=info.duration_s, turns=turns
    )
    case.asks = sum(1 for t in rec.load_turns(job_dir) if t.act and t.act.tool == "ask_person")
    return case


# --- state between runs (the open response and the call waiting for an answer) ---------------


def _state_path(job_dir: Path) -> Path:
    return rec.agent_dir(job_dir) / "state.json"


def load_state(job_dir: Path) -> dict:
    path = _state_path(job_dir)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_state(job_dir: Path, state: dict) -> None:
    artifacts.write_json_atomic(_state_path(job_dir), state)


# --- one model turn --------------------------------------------------------------------------


def image_message(case: Case, result: Result) -> dict:
    """A user message with the tool's image: the model only sees images in user messages."""
    path = case.path(result.image)
    mime = "image/png" if path.suffix == ".png" else "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "role": "user",
        "content": [
            {"type": "input_text", "text": f"Image from the last tool: {result.image}"},
            {"type": "input_image", "image_url": f"data:{mime};base64,{data}"},
        ],
    }


def tool_output(call_id: str, text: str) -> dict:
    return {"type": "function_call_output", "call_id": call_id, "output": text}


def first_call(response: Any) -> Any | None:
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", "") == "function_call":
            return item
    return None


def turn_cost(model: str, response: Any) -> tuple[int, float]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0.0
    details = getattr(usage, "input_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) or 0
    return usage.output_tokens, token_cost(model, usage.input_tokens, cached, usage.output_tokens)


def step(case: Case, settings: Settings, state: dict, pending_input: list) -> tuple[list, bool]:
    """Ask the model once, run its tool, save the turn. Returns (next input, stop)."""
    record = case.record
    nudge = []
    if record.turn + 1 >= record.max_turns:
        nudge = [{"role": "user", "content": "This is your last turn: call submit_guide now."}]
    follow_up = {"previous_response_id": state["response_id"]} if state.get("response_id") else {}
    request = {
        "model": settings.wonder_model,
        "tools": DEFINITIONS,
        "parallel_tool_calls": False,
        "reasoning": {"effort": EFFORT},
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }
    try:
        response = case.client.respond(input=pending_input + nudge, **request, **follow_up)
    except MetaError as exc:
        if exc.status_code != 400 or not follow_up:
            raise
        # Meta lost the open response: start a new conversation from what is already saved
        logger.warning("the open response is gone, restarting the conversation from the record")
        again = restart_input(case, state, pending_input)
        response = case.client.respond(input=again + nudge, **request)
    record.turn += 1  # only a call that answered counts as a turn
    state["response_id"] = response.id
    tokens, usd = turn_cost(settings.wonder_model, response)
    record.usd = round(record.usd + usd, 4)
    plan = (getattr(response, "output_text", "") or "").strip()[:600]
    call = first_call(response)
    if call is None:
        rec.append_turn(case.job_dir, Turn(turn=record.turn, plan=plan, tokens=tokens, usd=usd))
        rec.save_record(case.job_dir, record)
        reminder = "Continue with one tool call. When the guide is complete, call submit_guide."
        return [{"role": "user", "content": reminder}], False
    result = run_tool(case, call.name, call.arguments)
    if not result.ok:
        record.notes = (record.notes + [f"turn {record.turn} {call.name}: {result.text}"])[-20:]
    args = json.loads(call.arguments) if call.arguments else {}
    rec.append_turn(
        case.job_dir,
        Turn(
            turn=record.turn,
            plan=plan,
            tokens=tokens,
            usd=usd,
            act=Act(tool=call.name, args=args if isinstance(args, dict) else {}),
            observe=Observe(ok=result.ok, text=result.text, image=result.image),
        ),
    )
    if result.stop:
        state["pending_call"] = call.call_id
        rec.save_record(case.job_dir, record)
        return [], True
    rec.save_record(case.job_dir, record)
    next_input = [tool_output(call.call_id, ("OK: " if result.ok else "REFUSED: ") + result.text)]
    if result.image and case.path(result.image).exists():
        next_input.append(image_message(case, result))
    return next_input, False


# --- run and resume --------------------------------------------------------------------------


def opening_input(case: Case, file_id: str, info: IngestInfo) -> list:
    playbook = PROMPT.read_text(encoding="utf-8")
    return [
        {"role": "system", "content": playbook},
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": case_file(case.job_dir, case.record, info)},
                {"type": "input_file", "file_id": file_id},
            ],
        },
    ]


def restart_input(case: Case, state: dict, pending_input: list) -> list:
    """A new conversation that knows the turns so far; the tool's image still goes along."""
    info = artifacts.load(case.job_dir, IngestInfo)
    lines = ["Your earlier conversation was lost. What you already did, oldest first:"]
    for turn in rec.load_turns(case.job_dir):
        if turn.act and turn.observe:
            lines.append(f"{turn.turn}. {turn.act.tool} {turn.act.args}: {turn.observe.text[:300]}")
    recap = {"role": "user", "content": "\n".join(lines)}
    images = [item for item in pending_input if item.get("role") == "user"]
    return [*opening_input(case, state["file_id"], info), recap, *images]


def resume_input(job_dir: Path, record: AgentRecord, state: dict) -> list | None:
    """What to tell the model when a stopped run continues; None when there is nothing to do."""
    call_id = state.get("pending_call")
    if record.status == "needs_input":
        answer = rec.take_answer(job_dir)
        if answer is None:
            return None
        record.question = None
        return (
            [tool_output(call_id, f"The person answered: {answer}")]
            if call_id
            else [{"role": "user", "content": f"The person answered your question: {answer}"}]
        )
    if record.status == "awaiting_signoff":
        path = rec.agent_dir(job_dir) / "signoff.json"
        if not path.exists():
            return None
        signoff = SignOff.model_validate_json(path.read_text(encoding="utf-8"))
        path.unlink()
        record.signoff = signoff
        if signoff.approved:
            record.status = "done"
            return []
        text = f"The person asked for changes: {signoff.notes}. Fix them, then submit_guide again."
        return [tool_output(call_id, text)] if call_id else [{"role": "user", "content": text}]
    if record.status in ("paused", "failed"):
        record.max_turns = max(record.max_turns, record.turn) + MORE_TURNS
        return [{"role": "user", "content": f"Continue. You have {MORE_TURNS} more turns."}]
    return None


def run(
    job_dir: Path, settings: Settings, *, resume: bool = False, client: Any = None
) -> AgentRecord:
    """Run the agent until it stops. Always leaves a saved record behind."""
    job_dir = Path(job_dir)
    # the agent works after the guide pipeline: it gets its own allowance on top of the job's
    budget = settings.job_budget_usd + settings.agent_budget_usd
    client = client or make_client(replace(settings, job_budget_usd=budget), job_dir)
    info = artifacts.load(job_dir, IngestInfo)
    record = rec.load_record(job_dir)
    state = load_state(job_dir) if resume else {}
    if resume and record.status != "idle":
        pending = resume_input(job_dir, record, state)
        if pending is None:
            return record
    else:
        identity = artifacts.load_optional(job_dir, Identity)
        record = AgentRecord(
            objective=objective(identity, artifacts.load_optional(job_dir, Analysis))
        )
        record.max_turns = MAX_TURNS
        state = {}
        pending = None
    if record.status == "done":
        _forget_video(client, state)
        save_state(job_dir, state)
        rec.save_record(job_dir, record)
        return record
    record.status = "running"
    state["pending_call"] = None
    rec.save_record(job_dir, record)
    case = load_case(job_dir, client, record)
    try:
        if pending is None:
            state["file_id"] = client.upload_file(case.video)
            pending = opening_input(case, state["file_id"], info)
        save_state(job_dir, state)
        stop = False
        while not stop:
            if record.turn >= record.max_turns:
                record.status = "paused"
                record.notes.append("turn limit reached: resume for more turns")
                break
            pending, stop = step(case, settings, state, pending)
            save_state(job_dir, state)
    except BudgetExceeded as exc:
        record.status = "paused"
        record.notes.append(f"budget reached: {exc}")
    except (MetaError, OSError) as exc:
        logger.exception("agent turn failed")
        record.status = "paused"
        record.notes.append(f"model call failed, resume to retry: {exc}")
    save_state(job_dir, state)
    rec.save_record(job_dir, record)
    return record


def _forget_video(client: Any, state: dict) -> None:
    if state.get("file_id"):
        client.delete_file(state["file_id"])
        state["file_id"] = None


# --- background process ----------------------------------------------------------------------


def _lock(job_dir: Path) -> Path:
    return rec.agent_dir(job_dir) / "run.lock"


def is_running(job_dir: Path) -> bool:
    try:
        pid = int(_lock(job_dir).read_text().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def launch(job_dir: Path, *, resume: bool = False) -> bool:
    """Start (or resume) the agent for a job in the background. False if it is already running."""
    job_dir = Path(job_dir)
    if is_running(job_dir):
        return False
    if not resume and rec.load_record(job_dir).status in ("needs_input", "awaiting_signoff"):
        return False  # a fresh start would throw away a run that waits for the person
    rec.agent_dir(job_dir).mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "app.agent.loop", str(job_dir)] + (
        ["--resume"] if resume else []
    )
    with open(rec.agent_dir(job_dir) / "agent.log", "a") as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
    artifacts.write_text_atomic(_lock(job_dir), str(process.pid))
    return True


def main(argv: list[str] | None = None) -> int:
    from app.config import get_settings

    args = sys.argv[1:] if argv is None else argv
    resume = "--resume" in args
    args = [a for a in args if a != "--resume"]
    if len(args) != 1:
        print("usage: python -m app.agent.loop <job_dir> [--resume]")
        return 2
    logging.basicConfig(level=logging.INFO)
    record = run(Path(args[0]), get_settings(), resume=resume)
    print(f"agent: {record.status} after {record.turn} turns, ${record.usd:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
