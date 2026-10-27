from app.pipeline.assembly import build_reassembly, check_reassembly
from app.schemas import Box, ScrewMap, Step


def screws(*numbers):
    boxes = [Box(number=n, x=0.1 * n, y=0.2, w=0.05, h=0.05) for n in numbers]
    return ScrewMap(count=len(boxes), boxes=boxes)


def step(index, action=None, removes=(), target_part=None, screw_map=None):
    return Step(
        index=index,
        title=f"Step {index}",
        instruction="...",
        start_s=index * 10.0,
        end_s=index * 10.0 + 9,
        action=action,
        removes=list(removes),
        target_part=target_part,
        screws=screw_map,
    )


def phone_steps():
    return [
        step(1, "unscrew", ["back cover"], screw_map=screws(1, 2, 3, 4)),
        step(2, "inspect", target_part="battery"),
        step(3, "disconnect", ["battery connector"]),
        step(4, "remove", ["battery"], screw_map=screws(1, 2)),
    ]


def test_reverses_order_and_actions():
    result = build_reassembly(phone_steps())
    assert [s.source_step for s in result.steps] == [4, 3, 1]
    assert [s.action for s in result.steps] == ["install", "reconnect", "screw in"]
    assert [s.index for s in result.steps] == [1, 2, 3]
    assert result.warnings == []


def test_screws_go_back_to_the_same_places():
    result = build_reassembly(phone_steps())
    last = result.steps[-1]
    assert last.parts == ["back cover"]
    assert last.screws.count == 4
    assert last.screws == phone_steps()[0].screws
    assert "positions 1, 2, 3, 4" in last.instruction


def test_target_part_used_when_removes_is_empty():
    result = build_reassembly([step(1, "remove", target_part="SIM tray")])
    assert result.steps[0].parts == ["SIM tray"]
    assert result.steps[0].instruction == "Install SIM tray."


def test_screws_without_action_count_as_unscrew():
    result = build_reassembly([step(1, removes=["shield"], screw_map=screws(1))])
    assert result.steps[0].action == "screw in"


def test_warns_when_part_not_named():
    result = build_reassembly([step(1, "remove")])
    assert any("nothing is named" in w for w in result.warnings)


def test_warns_when_count_and_map_disagree():
    bad = ScrewMap(count=4, boxes=screws(1, 2, 3).boxes)
    result = build_reassembly([step(1, "unscrew", ["cover"], screw_map=bad)])
    assert any("4 screws counted but 3 located" in w for w in result.warnings)
    assert result.steps[0].warnings


def test_warns_when_unscrew_has_no_screws():
    result = build_reassembly([step(1, "unscrew", ["cover"])])
    assert any("not counted" in w for w in result.warnings)


def test_warns_when_part_removed_twice():
    result = build_reassembly([step(1, "remove", ["battery"]), step(2, "remove", ["Battery"])])
    assert any("already removed" in w for w in result.warnings)


def test_check_finds_missing_step_and_screws():
    steps = phone_steps()
    edited = build_reassembly(steps).steps[:-1]  # back cover never goes back
    warnings = check_reassembly(steps, edited)
    assert any(
        "Step 1 removed back cover and 4 screws, but it is never put back" in w for w in warnings
    )
    assert "Screw check: 6 screws removed, 2 put back." in warnings


def test_check_finds_lost_screw_and_moved_screw():
    steps = phone_steps()
    edited = build_reassembly(steps).steps
    cover = edited[-1]
    boxes = [b.model_copy() for b in cover.screws.boxes[:3]]
    boxes[0] = boxes[0].model_copy(update={"x": 0.5})
    edited[-1] = cover.model_copy(update={"screws": ScrewMap(count=3, boxes=boxes)})
    warnings = check_reassembly(steps, edited)
    assert any("4 screws removed but 3 put back" in w for w in warnings)
    assert any("screw 4 has no place" in w for w in warnings)
    assert any("screw 1 goes to a different position" in w for w in warnings)


def test_check_finds_wrong_order_and_missing_part():
    steps = phone_steps()
    edited = list(reversed(build_reassembly(steps).steps))
    edited[0] = edited[0].model_copy(update={"parts": []})
    warnings = check_reassembly(steps, edited)
    assert any(w.startswith("Order:") for w in warnings)
    assert any("'back cover' is not put back" in w for w in warnings)


def test_check_finds_bad_source_and_duplicates():
    steps = phone_steps()
    built = build_reassembly(steps).steps
    wrong = built[0].model_copy(update={"source_step": 2})
    warnings = check_reassembly(steps, [built[0], built[0], wrong])
    assert any("reversed twice" in w for w in warnings)
    assert any("points to step 2" in w for w in warnings)


def test_empty_guide():
    result = build_reassembly([])
    assert result.steps == []
    assert result.warnings == []


def test_the_reverse_of_an_assembly_takes_it_apart():
    from app.pipeline.assembly import build_reassembly
    from app.schemas import ScrewMap, Step

    steps = [
        Step(index=1, title="Join", instruction="i", start_s=0, end_s=5, action="attach",
             removes=["side rail"], screws=ScrewMap(count=4)),
        Step(index=2, title="Legs", instruction="i", start_s=5, end_s=9, action="insert",
             removes=["leg"]),
    ]  # fmt: skip
    result = build_reassembly(steps, "assemble")
    assert [item.action for item in result.steps] == ["pull out", "detach"]
