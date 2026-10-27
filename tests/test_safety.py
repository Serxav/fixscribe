import pytest

from app.safety import blocked_operations, evaluate, normalize, stricter
from app.schemas import Identity, Safety


def identity(**fields) -> Identity:
    base = {"object_name": "office chair", "category": "furniture", "task": "repair"}
    return Identity(**(base | fields))


def test_normalize_drops_accents_and_case():
    assert normalize("Tubería de GAS") == "tuberia de gas"


def test_no_identity_no_text_is_normal():
    assert evaluate(None) == Safety()


def test_ordinary_hazard_means_caution():
    safety = evaluate(identity(hazards=["heavy_part"]))
    assert safety.level == "caution"
    assert "heavy part" in safety.reasons[0]


@pytest.mark.parametrize("hazard", ["gas", "refrigerant", "airbag", "high_voltage_battery"])
def test_professional_hazards(hazard):
    assert evaluate(identity(hazards=[hazard])).level == "professional_only"


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("Hoy cambiamos la llave de gas de la cocina", "gas line"),
        ("fixing a small gas leak", "gas line"),
        ("abrimos el cuadro eléctrico", "electrical panel"),
        ("replace a breaker in the fuse box", "electrical panel"),
        ("quitar el airbag del volante", "airbag"),
        ("recargar gas del aire acondicionado", "refrigerant"),
        ("R-134a top up", "refrigerant"),
        ("unplug the orange cables", "high-voltage battery"),
        ("cambiar el condensador del microondas", "microwave high voltage"),
    ],
)
def test_professional_only_operations(text, rule):
    safety = evaluate(None, [text])
    assert safety.level == "professional_only"
    assert rule in safety.blocked


@pytest.mark.parametrize(
    "text",
    [
        "replace the gas cap on my car",  # fuel, not a gas line
        "the gas pedal sticks",
        "change the capacitor on this amplifier board",  # no microwave
        "cambiar la junta del grifo",
        "gasket of the washing machine door",
    ],
)
def test_ordinary_words_do_not_block(text):
    assert blocked_operations([text]) == []


def test_object_name_and_problem_are_checked():
    safety = evaluate(identity(object_name="gas boiler", category="appliance"))
    assert safety.level == "professional_only"


def test_prechecks_are_kept_and_deduplicated():
    safety = evaluate(None, prechecks=["Unplug it.", "Unplug it.", " "])
    assert safety.prechecks == ["Unplug it."]


def test_stricter_never_lowers():
    rules = evaluate(identity(hazards=["airbag"]))
    model = Safety(level="normal", reasons=["looks easy"])
    combined = stricter(rules, model)
    assert combined.level == "professional_only"
    assert combined.reasons[-1] == "looks easy"


def test_stricter_can_raise():
    combined = stricter(Safety(), Safety(level="caution", reasons=["swollen battery seen"]))
    assert combined.level == "caution"
    assert combined.reasons == ["swollen battery seen"]
