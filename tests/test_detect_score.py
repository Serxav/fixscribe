from eval.detect_score import score_photo, summary

SQUARE = [[100, 100], [200, 100], [200, 200], [100, 200]]


def mark(outline):
    xs = [x for x, _ in outline]
    ys = [y for _, y in outline]
    return {"outline": outline, "cut_box": [min(xs), min(ys), max(xs), max(ys)]}


def test_found_missed_false_and_merged():
    key = {"find": [["screw", 150, 150], ["screw", 180, 180], ["screw", 500, 500]]}
    far = mark([[800, 800], [850, 800], [850, 850], [800, 850]])
    result = score_photo([mark(SQUARE), far], key)
    assert result["found"] == 2
    assert result["missed"] == ["screw"]
    assert result["false"] == [1]
    assert result["merged"] == [0]


def test_optional_point_is_not_false_and_not_required():
    key = {"find": [], "optional": [["screw", 150, 150]]}
    result = score_photo([mark(SQUARE)], key)
    assert result["false"] == [] and result["expected"] == 0


def test_point_just_outside_outline_counts():
    result = score_photo([mark(SQUARE)], {"find": [["part", 205, 150]]})
    assert result["found"] == 1


def test_summary():
    good = {"expected": 2, "found": 2, "marks": 2, "false": [], "merged": [], "missed": []}
    bad = {"expected": 2, "found": 1, "marks": 2, "false": [1], "merged": [], "missed": ["x"]}
    assert summary({"a": good, "b": bad}) == {
        "recall": 0.75,
        "precision": 0.75,
        "perfect": 1,
        "photos": 2,
    }
