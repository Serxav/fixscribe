"""Deterministic safety rules, applied before and after any model.

A repair can be normal, need caution (warnings on every step) or be professional-only (we explain
what is involved but give no instructions). The level comes from fixed rules on the identified
object and on every word we have (speech, step text). A model may add hazards later, but only
`stricter()` combines decisions, so nothing can ever lower a level these rules set.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from app.schemas import Identity, Safety

LEVELS = ("normal", "caution", "professional_only")

# Hazards whose work belongs to a licensed professional, whatever the object.
PRO_HAZARDS = {
    "gas": "Gas lines and appliances must be worked on by a certified gas technician.",
    "refrigerant": "Refrigerant circuits need a certified technician and recovery equipment.",
    "airbag": "Airbags can deploy and injure; only a trained technician should remove them.",
    "high_voltage_battery": "Hybrid and electric vehicle high-voltage systems can kill.",
}
# Every other hazard means: warn on every step.


@dataclass(frozen=True)
class Rule:
    name: str
    patterns: tuple[str, ...]  # regexes on accent-free lower case text (Spanish and English)
    reason: str
    also_needs: tuple[str, ...] = ()  # all of these must match too (for context-dependent rules)


PRO_RULES = (
    Rule(
        "gas line",
        (
            r"\bgas (line|pipe|valve|leak|stove|boiler|heater|oven|hob|cooker|meter)s?\b",
            r"\b(tuberia|llave|fuga|escape|cocina|caldera|calentador|horno|estufa|contador)"
            r" de gas\b",
        ),  # not a bare "gas": "gas tank" or "gas pedal" on a car is not a gas line
        PRO_HAZARDS["gas"],
    ),
    Rule(
        "electrical panel",
        (
            r"\b(breaker|fuse|electrical|distribution) (panel|box|board)\b",
            r"\bconsumer unit\b",
            r"\bcuadro electrico\b",
            r"\b(caja|cuadro) de (fusibles|automaticos|distribucion)\b",
        ),
        "Work inside the main electrical panel needs a licensed electrician.",
    ),
    Rule("airbag", (r"\bairbags?\b",), PRO_HAZARDS["airbag"]),
    Rule(
        "refrigerant",
        (
            r"\brefrigerante?\b",
            r"\bfreon\b",
            r"\br-?(134a|600a|410a|32)\b",
            r"\brecargar? (el )?gas\b",
        ),
        PRO_HAZARDS["refrigerant"],
    ),
    Rule(
        "high-voltage battery",
        (
            r"\bhigh[- ]voltage battery\b",
            r"\b(hybrid|ev|traction) battery\b",
            r"\bbateria (de alta tension|hibrida|de traccion)\b",
            r"\borange (cable|wire)s?\b",
            r"\bcables? naranjas?\b",
        ),
        PRO_HAZARDS["high_voltage_battery"],
    ),
    Rule(
        "microwave high voltage",
        (r"\b(capacitor|condensador|magnetron|transformer|transformador)\b",),
        "A microwave's capacitor holds a lethal charge even when unplugged.",
        also_needs=(r"\b(microwave|microondas)\b",),
    ),
)


def normalize(text: str) -> str:
    """Lower case without accents, so 'Tubería' and 'tuberia' match the same rule."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _matches(patterns: Iterable[str], text: str) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def blocked_operations(texts: Iterable[str]) -> list[Rule]:
    """The professional-only rules that any of the texts trigger, in rule order."""
    text = normalize("\n".join(texts))
    return [
        rule
        for rule in PRO_RULES
        if _matches(rule.patterns, text) and all(re.search(p, text) for p in rule.also_needs)
    ]


def evaluate(
    identity: Identity | None, texts: Iterable[str] = (), prechecks: Iterable[str] = ()
) -> Safety:
    """The rules-only safety decision for a job.

    `texts` are every word we have about the job (object name, speech, step text);
    `prechecks` come from the domain profile and are always kept.
    """
    texts = list(texts)
    hazards = list(identity.hazards) if identity else []
    if identity:
        texts += [identity.object_name, identity.problem]
    reasons: list[str] = []
    blocked: list[str] = []
    level = "normal"
    for hazard in hazards:
        if hazard in PRO_HAZARDS:
            level = "professional_only"
            reasons.append(PRO_HAZARDS[hazard])
    for rule in blocked_operations(texts):
        level = "professional_only"
        reasons.append(rule.reason)
        blocked.append(rule.name)
    if level == "normal" and hazards:
        level = "caution"
        reasons.append("Hazards: " + ", ".join(h.replace("_", " ") for h in hazards) + ".")
    return Safety(
        level=level,
        reasons=_unique(reasons),
        prechecks=_unique(prechecks),
        blocked=_unique(blocked),
    )


def stricter(current: Safety, proposed: Safety) -> Safety:
    """Combine two decisions: the higher level wins and every reason, check and block is kept.

    This is the only way a model's opinion enters the safety decision, so it can never lower it.
    """
    level = max(current.level, proposed.level, key=LEVELS.index)
    return Safety(
        level=level,
        reasons=_unique(current.reasons + proposed.reasons),
        prechecks=_unique(current.prechecks + proposed.prechecks),
        blocked=_unique(current.blocked + proposed.blocked),
    )


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in items if item and item.strip()))
