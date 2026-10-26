"""Build the reassembly guide from the disassembly steps and check that nothing is left out.

Pure logic, no Meta calls. Spark rewrites the instruction text later; here we decide the order,
the reverse action, the parts and which screw goes where.
"""

from pydantic import BaseModel, Field

from app.schemas import ReassemblyStep, ScrewMap, Step

# Disassembly action -> the action that undoes it.
REVERSE_ACTIONS = {
    "remove": "install",
    "disconnect": "reconnect",
    "unscrew": "screw in",
    "unclip": "clip in",
    "pry": "press back",
    "open": "close",
    "peel": "re-apply",
}


class AssemblyResult(BaseModel):
    steps: list[ReassemblyStep] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def step_action(step: Step) -> str | None:
    """The disassembly action of a step, or None if the step does not take anything apart."""
    action = (step.action or "").strip().lower()
    if action in REVERSE_ACTIONS:
        return action
    if step.screws and step.screws.count > 0:
        return "unscrew"
    return None


def step_parts(step: Step) -> list[str]:
    if step.removes:
        return list(step.removes)
    return [step.target_part] if step.target_part else []


def screw_count(screws: ScrewMap | None) -> int:
    return screws.count if screws else 0


def screw_places(screws: ScrewMap | None) -> dict[int, tuple[float, float]]:
    """Screw number -> (x, y) of the box centre, rounded so tiny edits do not count."""
    if not screws:
        return {}
    return {
        box.number: (round(box.x + box.w / 2, 3), round(box.y + box.h / 2, 3))
        for box in screws.boxes
    }


def build_reassembly(steps: list[Step]) -> AssemblyResult:
    result = AssemblyResult()
    seen_parts: dict[str, int] = {}
    for step in reversed(steps):
        action = step_action(step)
        if action is None:
            continue
        parts = step_parts(step)
        notes = []
        if not parts:
            result.warnings.append(
                f"Step {step.index}: nothing is named as removed. Name the part so it can be "
                "put back."
            )
        for part in parts:
            key = part.strip().lower()
            if key in seen_parts:
                result.warnings.append(
                    f"Step {step.index}: '{part}' was already removed in step {seen_parts[key]}."
                )
            seen_parts[key] = step.index
        if action == "unscrew" and screw_count(step.screws) == 0:
            notes.append("Screws were removed here but not counted. Check the video.")
        if step.screws and step.screws.count != len(step.screws.boxes):
            notes.append(
                f"{step.screws.count} screws counted but {len(step.screws.boxes)} located on "
                "the screw map."
            )
        result.warnings.extend(f"Step {step.index}: {note}" for note in notes)
        result.steps.append(
            ReassemblyStep(
                index=len(result.steps) + 1,
                source_step=step.index,
                action=REVERSE_ACTIONS[action],
                instruction=draft_instruction(REVERSE_ACTIONS[action], parts, step.screws),
                parts=parts,
                screws=step.screws.model_copy(deep=True) if step.screws else None,
                warnings=notes,
            )
        )
    result.warnings.extend(check_reassembly(steps, result.steps))
    return result


def draft_instruction(action: str, parts: list[str], screws: ScrewMap | None) -> str:
    """A plain first draft. Spark rewrites it later."""
    what = ", ".join(parts) if parts else "the part"
    text = f"{action.capitalize()} {what}."
    count = screw_count(screws)
    if count:
        numbers = ", ".join(str(box.number) for box in sorted(screws.boxes, key=lambda b: b.number))
        text += f" {count} screw{'s' if count != 1 else ''}"
        text += f" (positions {numbers} on the screw map)." if numbers else "."
    return text


def check_reassembly(steps: list[Step], reassembly: list[ReassemblyStep]) -> list[str]:
    """Compare a reassembly (built here or edited later) with the disassembly steps."""
    warnings = []
    by_index = {step.index: step for step in steps}
    taken_apart = [step for step in steps if step_action(step)]
    used: dict[int, ReassemblyStep] = {}

    for item in reassembly:
        source = by_index.get(item.source_step)
        if source is None or not step_action(source):
            warnings.append(
                f"Reassembly step {item.index} points to step {item.source_step}, "
                "which takes nothing apart."
            )
            continue
        if item.source_step in used:
            warnings.append(
                f"Step {item.source_step} is reversed twice "
                f"(reassembly steps {used[item.source_step].index} and {item.index})."
            )
            continue
        used[item.source_step] = item
        warnings.extend(compare_step(source, item))

    for step in taken_apart:
        if step.index not in used:
            what = ", ".join(step_parts(step)) or "a part"
            screws = screw_count(step.screws)
            extra = f" and {screws} screws" if screws else ""
            warnings.append(f"Step {step.index} removed {what}{extra}, but it is never put back.")

    order = [item.source_step for item in reassembly if item.source_step in used]
    for earlier, later in zip(order, order[1:], strict=False):
        if earlier < later:
            warnings.append(
                f"Order: step {later} is undone after step {earlier}, but it was taken apart "
                "later. Undo the last removed part first."
            )

    removed = sum(screw_count(step.screws) for step in taken_apart)
    put_back = sum(screw_count(item.screws) for item in used.values())
    if removed != put_back:
        warnings.append(f"Screw check: {removed} screws removed, {put_back} put back.")
    return warnings


def compare_step(source: Step, item: ReassemblyStep) -> list[str]:
    warnings = []
    label = f"Reassembly step {item.index} (undoes step {source.index})"
    missing_parts = {p.lower() for p in step_parts(source)} - {p.lower() for p in item.parts}
    for part in sorted(missing_parts):
        warnings.append(f"{label}: '{part}' is not put back.")
    removed, back = screw_count(source.screws), screw_count(item.screws)
    if removed != back:
        warnings.append(f"{label}: {removed} screws removed but {back} put back.")
    places, back_places = screw_places(source.screws), screw_places(item.screws)
    for number, place in sorted(places.items()):
        if number not in back_places:
            warnings.append(f"{label}: screw {number} has no place.")
        elif back_places[number] != place:
            warnings.append(f"{label}: screw {number} goes to a different position.")
    return warnings
