"""Export a guide as a clean, readable Markdown file (task 039). Pure function, no web."""

import re

from app.schemas import Guide
from app.text import plural

FOOTER = "Made with FixScribe — Muse Spark, Muse Voice and SAM 3.1 by Meta."

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(title: str) -> str:
    """'Replace the Battery!' -> 'replace-the-battery': lower case a-z0-9 and dashes, max 60."""
    slug = _SLUG_RE.sub("-", title.lower()).strip("-")
    if len(slug) > 60:
        slug = slug[:60].strip("-")
    return slug or "guide"


def _mmss(seconds: float) -> str:
    """12.0 -> '0:12', 91.0 -> '1:31': minutes without padding, seconds with."""
    total = max(0, int(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _proof_line(guide: Guide, step_index: int) -> str:
    """'Proof: 2 verified · 1 supported · 1 unverified' for one step, or '' when unknown."""
    if guide.proof is None:
        return ""
    entry = next((item for item in guide.proof.steps if item.index == step_index), None)
    if entry is None or not entry.claims:
        return ""
    counts = {"verified": 0, "supported": 0, "unverified": 0}
    for claim in entry.claims:
        counts[claim.status] += 1
    parts = [f"{counts[status]} {status}" for status in counts if counts[status]]
    return f"Proof: {' · '.join(parts)}" if parts else ""


def _step_block(guide: Guide, step) -> list[str]:
    lines = [f"### {step.index}. {step.title}", "", step.instruction, ""]
    if step.screws is not None and step.screws.count > 0:
        kind = plural(step.screws.kind, step.screws.count)
        lines += [f"Fasteners: {step.screws.count} {kind}", ""]
    for warning in step.warnings:
        lines += [f"> ⚠ {warning}", ""]
    lines += [f"Video: {_mmss(step.start_s)}–{_mmss(step.end_s)}", ""]
    proof = _proof_line(guide, step.index)
    if proof:
        lines += [proof, ""]
    return lines


def guide_markdown(guide: Guide, job_id: str) -> str:
    """The whole guide as Markdown. `job_id` is kept so the route reads naturally."""
    _ = job_id
    if guide.identity is not None:
        subject = f"{guide.identity.object_name} ({guide.identity.category})"
    else:
        subject = guide.device
    steps = f"{len(guide.steps)} {plural('step', len(guide.steps))}"
    lines = [
        f"# {guide.title}",
        "",
        f"{subject} · {guide.difficulty} · ~{guide.estimated_minutes} min · {steps}",
        "",
    ]
    safety = guide.safety
    level = safety.level if safety is not None else "normal"
    if level == "caution" and safety is not None:
        lines += ["## Before you start", ""]
        lines += [f"- [ ] {precheck}" for precheck in safety.prechecks]
        if safety.prechecks:
            lines += [""]
        lines += [f"- {reason}" for reason in safety.reasons]
        if safety.reasons:
            lines += [""]
    elif level == "professional_only" and safety is not None:
        lines += ["## Professional only", ""]
        lines += [f"- {reason}" for reason in safety.reasons]
        if safety.reasons:
            lines += [""]
    prechecks = safety.prechecks if safety is not None else []
    warnings = [w for w in guide.warnings if w not in prechecks]  # prechecks are listed above
    if warnings:
        lines += ["## Warnings", ""]
        lines += [f"> ⚠ {warning}" for warning in warnings]
        lines += [""]
    if guide.tools:
        lines += ["## Tools", ""]
        lines += [f"- {tool}" for tool in guide.tools]
        lines += [""]
    if guide.parts:
        lines += ["## Parts", ""]
        lines += [f"- {part}" for part in guide.parts]
        lines += [""]
    if guide.steps:
        lines += ["## Steps", ""]
        for step in guide.steps:
            lines += _step_block(guide, step)
    if guide.reassembly:
        lines += ["## Reassembly", ""]
        lines += [f"{item.index}. {item.instruction}" for item in guide.reassembly]
        lines += [""]
    if guide.checks:
        lines += ["## Automatic checks", ""]
        lines += [f"- {check}" for check in guide.checks]
        lines += [""]
    lines += [FOOTER, ""]
    return "\n".join(lines)
