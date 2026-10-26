from app.schemas import ANALYSIS_JSON_SCHEMA, Analysis, DraftStep


def walk_objects(schema):
    if schema.get("type") == "object":
        yield schema
        for child in schema["properties"].values():
            yield from walk_objects(child)
    if schema.get("type") == "array":
        yield from walk_objects(schema["items"])


def test_schema_is_strict_everywhere():
    objects = list(walk_objects(ANALYSIS_JSON_SCHEMA))
    assert len(objects) == 3  # analysis, step, evidence
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert obj["required"] == list(obj["properties"])


def test_schema_keys_match_the_models():
    assert set(ANALYSIS_JSON_SCHEMA["properties"]) == set(Analysis.model_fields)
    step_schema = ANALYSIS_JSON_SCHEMA["properties"]["steps"]["items"]
    assert set(step_schema["properties"]) == set(DraftStep.model_fields)


def test_a_schema_shaped_answer_validates():
    answer = {
        "title": "Replace the battery",
        "device": "Phone X",
        "summary": "s",
        "difficulty": "easy",
        "estimated_minutes": 15,
        "tools": ["Phillips #000"],
        "parts": ["battery"],
        "warnings": [],
        "steps": [
            {
                "title": "Remove back cover",
                "instruction": "Remove the four screws.",
                "start_s": 1.5,
                "end_s": 12.0,
                "target_part": "back cover",
                "action": "unscrew",
                "removes": ["back cover"],
                "screw_count": 4,
                "warnings": [],
                "evidence": [{"t_s": 3.0, "source": "video", "text": "screws out"}],
                "confidence": 0.8,
            }
        ],
    }
    analysis = Analysis.model_validate(answer)
    assert analysis.steps[0].screw_count == 4


def test_refine_schema_is_strict_and_matches_the_model():
    from app.schemas import REFINE_JSON_SCHEMA, RefinedStep

    assert REFINE_JSON_SCHEMA["additionalProperties"] is False
    assert REFINE_JSON_SCHEMA["required"] == list(REFINE_JSON_SCHEMA["properties"])
    assert set(REFINE_JSON_SCHEMA["properties"]) == set(RefinedStep.model_fields) - {"index"}
