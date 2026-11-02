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
    # building actions: the reverse guide of an assembly takes it apart
    "place": "remove",
    "insert": "pull out",
    "attach": "detach",
    "screw in": "unscrew",
    "connect": "disconnect",
    "flip": "flip back",
}


# Actions that leave a part off in a repair video; every other action puts something on.
# "flip" counts too: whatever was turned over is turned back.
TAKE_APART = frozenset({"remove", "disconnect", "unscrew", "unclip", "pry", "open", "peel", "flip"})
ARTICLES = ("the ", "a ", "an ", "both ", "all ", "each ")


class AssemblyResult(BaseModel):
    steps: list[ReassemblyStep] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def step_action(step: Step, direction: str = "disassemble") -> str | None:
    """The action the reverse guide undoes, or None if the step changes nothing to undo."""
    action = (step.action or "").strip().lower()
    if action in REVERSE_ACTIONS:
        return action
    if step.screws and step.screws.count > 0:
        return "screw in" if direction == "assemble" else "unscrew"
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


def _key(part: str) -> str:
    return part.strip().lower()


def parts_still_off(steps: list[Step], direction: str = "disassemble") -> dict[int, list[str]]:
    """Step index -> the parts that step took off and that are still off at the end of the video.

    A real repair video is not a clean teardown: a cover comes off, goes back for a test and comes
    off again; a new battery goes in. Every removal since a part was last put on is undone
    ("unscrew the cover", then "remove the cover"), but the same action repeated on the same part
    counts once, the last time: it was undone off camera. A taking-apart step that names no part
    is kept with no parts: there is nothing to follow. The reverse of an assembly video takes
    apart everything it built.
    """
    acting = [step for step in steps if step_action(step, direction)]
    if direction == "assemble":
        return {step.index: step_parts(step) for step in acting}
    open_: dict[str, list[tuple[int, str]]] = {}  # part -> (step, action) since last put on
    for step in acting:
        action = step_action(step, direction)
        for part in step_parts(step):
            key = _key(part)
            if action not in TAKE_APART:
                open_.pop(key, None)
                continue
            earlier = [entry for entry in open_.get(key, []) if entry[1] != action]
            open_[key] = [*earlier, (step.index, action)]
    off: dict[int, set[str]] = {}
    for key, entries in open_.items():
        for index, _ in entries:
            off.setdefault(index, set()).add(key)
    result: dict[int, list[str]] = {}
    for step in acting:
        if step_action(step, direction) not in TAKE_APART:
            continue
        parts = step_parts(step)
        if not parts:
            result[step.index] = []
        elif step.index in off:
            result[step.index] = [part for part in parts if _key(part) in off[step.index]]
    return result


def steps_to_undo(steps: list[Step], direction: str = "disassemble") -> list[Step]:
    """The steps the reverse guide undoes, in video order (see ``parts_still_off``)."""
    still_off = parts_still_off(steps, direction)
    return [step for step in steps if step.index in still_off]


def removed_twice(steps: list[Step], direction: str = "disassemble") -> list[str]:
    """The same action on the same part again, with nothing putting it back in between: the
    analysis may be off, or the video skipped a step."""
    if direction == "assemble":
        return []
    off: dict[tuple[str, str], int] = {}
    warnings = []
    for step in steps:
        action = step_action(step, direction)
        if action is None:
            continue
        for part in step_parts(step):
            if action not in TAKE_APART:
                for key in [k for k in off if k[0] == _key(part)]:
                    del off[key]
            elif (_key(part), action) in off:
                warnings.append(
                    f"Step {step.index}: '{part}' was already removed in step "
                    f"{off[(_key(part), action)]}."
                )
            else:
                off[(_key(part), action)] = step.index
    return warnings


def build_reassembly(steps: list[Step], direction: str = "disassemble") -> AssemblyResult:
    """The reverse guide: reassembly of a repair, or taking apart what an assembly built."""
    result = AssemblyResult(warnings=removed_twice(steps, direction))
    still_off = parts_still_off(steps, direction)
    for step in reversed(steps_to_undo(steps, direction)):
        action = step_action(step, direction)
        parts = still_off[step.index]
        notes = []
        if not parts:
            result.warnings.append(
                f"Step {step.index}: nothing is named as removed. Name the part so it can be "
                "put back."
            )
        if action == "unscrew" and screw_count(step.screws) == 0:
            notes.append("Screws were removed here but not counted. Check the video.")
        # No boxes yet means SAM has not looked for the screws: nothing to compare.
        if step.screws and step.screws.boxes and step.screws.count != len(step.screws.boxes):
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
    result.warnings.extend(check_reassembly(steps, result.steps, direction))
    return result


def _the(part: str) -> str:
    """ "back cover" -> "the back cover", so "press back" never reads "press back back cover"."""
    return part if part.lower().startswith(ARTICLES) else f"the {part}"


def draft_instruction(action: str, parts: list[str], screws: ScrewMap | None) -> str:
    """A plain first draft. Spark rewrites it later."""
    what = ", ".join(_the(part) for part in parts) if parts else "the part"
    text = f"{action.capitalize()} {what}."
    count = screw_count(screws)
    if count:
        numbers = [str(box.number) for box in sorted(screws.boxes, key=lambda b: b.number)]
        text += f" {count} screw{'s' if count != 1 else ''}"
        if not numbers:
            text += "."
        elif len(numbers) < count:
            plural = "s" if len(numbers) > 1 else ""
            text += f" ({len(numbers)} on the screw map: position{plural} {', '.join(numbers)})."
        else:
            text += f" (position{'s' if count > 1 else ''} {', '.join(numbers)} on the screw map)."
    return text


def check_reassembly(
    steps: list[Step], reassembly: list[ReassemblyStep], direction: str = "disassemble"
) -> list[str]:
    """Compare a reassembly (built here or edited later) with the disassembly steps."""
    warnings = []
    still_off = parts_still_off(steps, direction)
    taken_apart = steps_to_undo(steps, direction)
    by_index = {step.index: step for step in taken_apart}
    used: dict[int, ReassemblyStep] = {}

    for item in reassembly:
        source = by_index.get(item.source_step)
        if source is None:
            warnings.append(
                f"Reassembly step {item.index} points to step {item.source_step}, "
                "which leaves nothing off at the end of the video."
            )
            continue
        if item.source_step in used:
            warnings.append(
                f"Step {item.source_step} is reversed twice "
                f"(reassembly steps {used[item.source_step].index} and {item.index})."
            )
            continue
        used[item.source_step] = item
        warnings.extend(compare_step(source, item, still_off[source.index]))

    for step in taken_apart:
        if step.index not in used:
            what = ", ".join(still_off[step.index]) or "a part"
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


def compare_step(source: Step, item: ReassemblyStep, parts: list[str] | None = None) -> list[str]:
    warnings = []
    label = f"Reassembly step {item.index} (undoes step {source.index})"
    wanted = step_parts(source) if parts is None else parts
    missing_parts = {p.lower() for p in wanted} - {p.lower() for p in item.parts}
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
