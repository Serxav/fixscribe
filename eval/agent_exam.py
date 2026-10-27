"""Grade an agent run against a hand-written answer key.

Usage:
    python -m eval.agent_exam <job_dir> <key.json>

Like Meta's agent workshop "checklist vs ground truth": did the agent find the
right parts, in the right place, and the right steps in the right order?
No Meta calls. Answer keys of private videos live in samples/ (gitignored).
"""

import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

from app import artifacts
from app.agent import record
from app.agent.record import AgentRecord, Part
from eval.score import match_steps

PLACE_TOL_S = 1.0  # agent and key times must be this close for a place check
PLACE_IOU = 0.3  # boxes showing the same part overlap at least this much


def _norm(text: str) -> str:
    """Lower case, no accents, no punctuation, single spaces."""
    folded = unicodedata.normalize("NFKD", text.casefold())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^\w\s]", " ", folded).split())


def load_key(path: Path) -> dict:
    """Read and check an answer key file; ValueError with a clear message if wrong."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read answer key {path}: {exc.strerror or exc}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"answer key {path} is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise ValueError(f"answer key {path} must be a JSON object")
    if "video" in data and not isinstance(data["video"], str):
        raise ValueError(f"answer key {path}: 'video' must be a string")
    for field in ("parts", "steps"):
        if not isinstance(data.get(field), list):
            raise ValueError(f"answer key {path} needs a '{field}' list")
    parts = [_check_part(path, pos, item) for pos, item in enumerate(data["parts"])]
    steps = [_check_step(path, pos, item) for pos, item in enumerate(data["steps"])]
    return {"video": data.get("video", ""), "parts": parts, "steps": steps}


def _is_num(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _check_part(path: Path, pos: int, item: Any) -> dict:
    if not isinstance(item, dict):
        raise ValueError(f"answer key {path}: part {pos} must be an object")
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"answer key {path}: part {pos} needs a 'name' string")
    aliases = item.get("aliases", [])
    if not isinstance(aliases, list) or any(not isinstance(a, str) for a in aliases):
        raise ValueError(f"answer key {path}: part {name!r} needs an 'aliases' string list")
    count = item.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError(f"answer key {path}: part {name!r} needs a 'count' integer >= 1")
    t_s = item.get("t_s")
    if not _is_num(t_s) or t_s < 0:
        raise ValueError(f"answer key {path}: part {name!r} needs a 't_s' number >= 0")
    box = item.get("box")
    if box is not None and (
        not isinstance(box, list) or len(box) != 4 or not all(_is_num(v) for v in box)
    ):
        raise ValueError(f"answer key {path}: part {name!r} needs a 'box' of 4 numbers or null")
    return {
        "name": name,
        "aliases": aliases,
        "count": count,
        "t_s": float(t_s),
        "box": [float(v) for v in box] if box is not None else None,
    }


def _check_step(path: Path, pos: int, item: Any) -> dict:
    if not isinstance(item, dict):
        raise ValueError(f"answer key {path}: step {pos} must be an object")
    action = item.get("action")
    if not isinstance(action, str) or not action.strip():
        raise ValueError(f"answer key {path}: step {pos} needs an 'action' string")
    step_parts = item.get("parts", [])
    if not isinstance(step_parts, list) or any(not isinstance(p, str) for p in step_parts):
        raise ValueError(f"answer key {path}: step {pos} needs a 'parts' string list")
    start_s, end_s = item.get("start_s"), item.get("end_s")
    if not _is_num(start_s) or not _is_num(end_s) or start_s < 0 or not start_s < end_s:
        raise ValueError(f"answer key {path}: step {pos} needs 0 <= 'start_s' < 'end_s'")
    return {
        "action": action,
        "parts": step_parts,
        "start_s": float(start_s),
        "end_s": float(end_s),
    }


def _part_matches(agent_name: str, key_part: dict) -> bool:
    """The agent name means the key part: same normalized name, an alias, or all key words."""
    wanted = {_norm(key_part["name"]), *(_norm(a) for a in key_part["aliases"])}
    if _norm(agent_name) in wanted:
        return True
    key_words = _norm(key_part["name"]).split()
    agent_words = set(_norm(agent_name).split())
    return bool(key_words) and all(word in agent_words for word in key_words)


def match_parts(agent_parts: list[Part], key_parts: list[dict]) -> list[tuple[str, str]]:
    """(agent id, key name) pairs; each agent part and each key part used at most once."""
    pairs, used_keys = [], set()
    for agent in agent_parts:
        for pos, key_part in enumerate(key_parts):
            if pos not in used_keys and _part_matches(agent.name, key_part):
                pairs.append((agent.id, key_part["name"]))
                used_keys.add(pos)
                break
    return pairs


def box_iou(a: list[float], b: list[float]) -> float:
    """Intersection over union of two 0..1000 boxes [x_min, y_min, x_max, y_max]."""
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def grade(assoc_record: AgentRecord, key: dict, turns: list | None = None) -> dict:
    """Score the agent record against the key; turns add questions, refusals and cost."""
    turns = turns if turns is not None else []
    pairs = match_parts(assoc_record.parts, key["parts"])
    by_id = {part.id: part for part in assoc_record.parts}
    by_name = {part["name"]: part for part in key["parts"]}
    agent_to_key = dict(pairs)

    parts_found = len(pairs)
    parts_expected = len(key["parts"])
    parts_extra = len(assoc_record.parts) - parts_found
    count_right = sum(
        1 for agent_id, name in pairs if by_id[agent_id].count == by_name[name]["count"]
    )

    place_right, place_checkable = 0, 0
    for agent_id, name in pairs:
        agent, wanted = by_id[agent_id], by_name[name]
        if agent.box is None or wanted["box"] is None:
            continue
        if abs(agent.t_s - wanted["t_s"]) > PLACE_TOL_S:
            continue
        place_checkable += 1
        if box_iou(list(agent.box), list(wanted["box"])) >= PLACE_IOU:
            place_right += 1

    found = [{"start_s": s.start_s, "end_s": s.end_s} for s in assoc_record.steps]
    expected = [{"start_s": s["start_s"], "end_s": s["end_s"]} for s in key["steps"]]
    matches = match_steps(found, expected)
    by_n = {n: s for n, s in enumerate(assoc_record.steps)}
    action_right, parts_right = 0, 0
    for found_pos, expected_pos, _ in matches:
        agent_step, wanted_step = by_n[found_pos], key["steps"][expected_pos]
        if _norm(agent_step.action) == _norm(wanted_step["action"]):
            action_right += 1
        mapped = [agent_to_key.get(pid) for pid in agent_step.parts]
        if all(mapped) and set(mapped) == set(wanted_step["parts"]):
            parts_right += 1
    found_order = [found_pos for found_pos, _, _ in matches]
    order_right = found_order == sorted(found_order)

    steps = assoc_record.steps
    verified_share = round(sum(s.verified for s in steps) / len(steps), 3) if steps else 0.0
    questions_asked = sum(1 for t in turns if t.act is not None and t.act.tool == "ask_person")
    refusals = sum(1 for t in turns if t.observe is not None and not t.observe.ok)

    parts_recall = parts_found / parts_expected if parts_expected else 0.0
    place_share = place_right / place_checkable if place_checkable else 1.0
    steps_recall = len(matches) / len(expected) if expected else 0.0
    action_share = action_right / len(matches) if matches else 0.0
    order_share = 1.0 if order_right and matches else 0.0  # no matched steps earns no order points
    final = round(
        100
        * (
            0.3 * parts_recall
            + 0.2 * place_share
            + 0.3 * steps_recall
            + 0.1 * action_share
            + 0.1 * order_share
        )
    )

    matched_names = {name for _, name in pairs}
    return {
        "parts_found": parts_found,
        "parts_expected": parts_expected,
        "parts_extra": parts_extra,
        "count_right": count_right,
        "place_right": place_right,
        "place_checkable": place_checkable,
        "steps_found": len(matches),
        "steps_expected": len(expected),
        "steps_extra": len(found) - len(matches),
        "action_right": action_right,
        "parts_right": parts_right,
        "order_right": order_right,
        "verified_share": verified_share,
        "questions_asked": questions_asked,
        "refusals": refusals,
        "turns": len(turns),
        "usd": assoc_record.usd,
        "missed_parts": [p["name"] for p in key["parts"] if p["name"] not in matched_names],
        "missed_steps": [
            f"{s['action']} ({s['start_s']:.1f}-{s['end_s']:.1f} s)"
            for pos, s in enumerate(key["steps"])
            if pos not in {expected_pos for _, expected_pos, _ in matches}
        ],
        "grade": final,
    }


def report(result: dict) -> str:
    """One Markdown table with the numbers, plus the missed parts and steps."""
    lines = [
        f"# Agent exam: {result['grade']}/100",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| Parts | {result['parts_found']}/{result['parts_expected']} "
        f"(extra {result['parts_extra']}, count right {result['count_right']}) |",
        f"| Place | {result['place_right']}/{result['place_checkable']} boxes (IoU >= 0.3) |",
        f"| Steps | {result['steps_found']}/{result['steps_expected']} "
        f"(extra {result['steps_extra']}) |",
        f"| Actions right | {result['action_right']}/{result['steps_found']} |",
        f"| Step parts right | {result['parts_right']}/{result['steps_found']} |",
        f"| Order right | {'yes' if result['order_right'] else 'no'} |",
        f"| Verified steps | {result['verified_share']:.0%} |",
        f"| Questions asked | {result['questions_asked']} |",
        f"| Refusals | {result['refusals']} |",
        f"| Turns | {result['turns']} |",
        f"| Cost | ${result['usd']:.4f} |",
        "",
        _missed_line("Missed parts", result["missed_parts"]),
        _missed_line("Missed steps (times)", result["missed_steps"]),
    ]
    return "\n".join(lines)


def _missed_line(label: str, items: list[str]) -> str:
    return f"{label}: {', '.join(items) if items else 'none'}"


def main(argv: list[str] | None = None) -> int:
    """Grade the agent run in a job folder; 2 on bad usage, 1 without a key or record."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m eval.agent_exam <job_dir> <key.json>")
        return 2
    job_dir, key_path = Path(args[0]), Path(args[1])
    try:
        key = load_key(key_path)
    except ValueError as exc:
        print(exc)
        return 1
    assoc_record = record.load_record(job_dir)
    if assoc_record.status == "idle":
        print(f"no agent record in {job_dir}: the agent never ran")
        return 1
    result = grade(assoc_record, key, record.load_turns(job_dir))
    print(report(result))
    artifacts.write_json_atomic(record.agent_dir(job_dir) / "exam.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
