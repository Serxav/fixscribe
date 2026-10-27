"""Narrate stage: Spark writes the spoken script of the repair film.

Text only, no video. One intro, one line per step for taking apart and one for
putting back, and two outros. The web page speaks them with the device voice.
"""

from pathlib import Path

from app import artifacts, spark
from app.config import Settings
from app.meta_client import MetaClient, make_client
from app.pipeline.assembly import AssemblyResult, build_reassembly
from app.schemas import (
    NARRATION_JSON_SCHEMA,
    Identity,
    Narration,
    NarrationLine,
    Plan,
    Safety,
    Step,
)

VERSION = "1"
MAX_OUTPUT_TOKENS = 4000
PROFESSIONAL_LINE = "A qualified professional must do this step."

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "narrate_v1.md"

WORDS_PER_SECOND = 2.6
MIN_WORDS = 12


class NarrateError(Exception):
    """Raised when the narrate inputs or the Spark answer are unusable."""


def step_seconds(step: Step) -> float:
    """How long the voice has for this step's line."""
    return max(0.0, step.end_s - step.start_s)


def word_limit(step: Step) -> int:
    """Words a voice says in the step's time, never fewer than MIN_WORDS."""
    return max(MIN_WORDS, round(step_seconds(step) * WORDS_PER_SECOND))


def cut_words(text: str, limit: int) -> str:
    """Strip and cut to `limit` words, ending with "…" when cut."""
    words = text.strip().split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]) + "…"


def describe_fasteners(step: Step) -> str:
    """Short fastener summary for the <<STEPS>> prompt block."""
    screws = step.screws
    if not screws or screws.count <= 0:
        return "none"
    kind = (screws.kind or "screw").strip() or "screw"
    if screws.count > 1 and not kind.endswith("s"):
        kind += "s"
    return f"{screws.count} {kind}"


def describe_step(step: Step) -> str:
    """One prompt line per step: title, instruction, time, fasteners, warnings."""
    warnings = ", ".join(step.warnings) if step.warnings else "none"
    return (
        f"{step.index}. {step.title} | {step.instruction} | "
        f"{step_seconds(step):.1f} s | fasteners: {describe_fasteners(step)} | "
        f"warnings: {warnings}"
    )


def build_prompt(
    plan: Plan,
    identity: Identity | None,
    safety: Safety | None,
    reassembly: AssemblyResult,
) -> str:
    """Fill the narrate prompt template with the plan, reassembly and safety."""
    language = (identity.language if identity else "") or "en"
    if identity and identity.object_name:
        obj = identity.object_name
    else:
        obj = plan.device
    steps_text = "\n".join(describe_step(step) for step in plan.steps) or "(no steps)"
    if reassembly.steps:
        reassembly_text = "\n".join(
            f"{item.index}. {item.instruction} (undoes step {item.source_step})"
            for item in reassembly.steps
        )
    else:
        reassembly_text = "(nothing to put back)"
    if safety is None:
        safety_text = "level: normal (no safety info)"
    else:
        prechecks = "; ".join(safety.prechecks) if safety.prechecks else "none"
        safety_text = f"level: {safety.level}; prechecks: {prechecks}"
    template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.replace("<<LANGUAGE>>", language)
    prompt = prompt.replace("<<OBJECT>>", obj)
    prompt = prompt.replace("<<STEPS>>", steps_text)
    prompt = prompt.replace("<<REASSEMBLY>>", reassembly_text)
    return prompt.replace("<<SAFETY>>", safety_text)


def apply_rules(plan: Plan, answer: dict, language: str, safety: Safety | None) -> Narration:
    """Clean Spark's answer into a Narration, or raise NarrateError.

    Keeps only step indexes that exist in the plan (one line per plan step),
    fills missing lines from the step and reassembly instructions, cuts each
    line to what the voice can say in the step's time, and overrides every
    line when the job is for professionals only.
    """
    if not isinstance(answer, dict):
        raise NarrateError("Spark returned an invalid narration")
    language = (language or "").strip() or "en"
    raw_steps = answer.get("steps", [])
    by_index: dict[int, dict] = {}
    if isinstance(raw_steps, list):
        for entry in raw_steps:
            if not isinstance(entry, dict):
                continue
            index = entry.get("index")
            if isinstance(index, bool) or not isinstance(index, int):
                continue
            by_index.setdefault(index, entry)
    reassembly = build_reassembly(plan.steps)
    reassembly_text = {item.source_step: item.instruction for item in reassembly.steps}
    lines: list[NarrationLine] = []
    for step in plan.steps:
        limit = word_limit(step)
        entry = by_index.get(step.index, {})
        disassemble = entry.get("disassemble") if isinstance(entry, dict) else None
        assemble = entry.get("assemble") if isinstance(entry, dict) else None
        disassemble = disassemble.strip() if isinstance(disassemble, str) else ""
        assemble = assemble.strip() if isinstance(assemble, str) else ""
        if not disassemble:
            disassemble = step.instruction.strip()
        if not assemble:
            assemble = (reassembly_text.get(step.index) or step.instruction).strip()
        lines.append(
            NarrationLine(
                index=step.index,
                disassemble=cut_words(disassemble, limit),
                assemble=cut_words(assemble, limit),
            )
        )
    intro = answer.get("intro") if isinstance(answer.get("intro"), str) else ""
    outro_disassemble = (
        answer.get("outro_disassemble") if isinstance(answer.get("outro_disassemble"), str) else ""
    )
    outro_assemble = (
        answer.get("outro_assemble") if isinstance(answer.get("outro_assemble"), str) else ""
    )
    if safety is not None and safety.level == "professional_only":
        reasons = "; ".join(reason.strip() for reason in safety.reasons if reason.strip())
        intro = reasons or intro.strip()
        lines = [
            NarrationLine(
                index=line.index, disassemble=PROFESSIONAL_LINE, assemble=PROFESSIONAL_LINE
            )
            for line in lines
        ]
    else:
        intro = intro.strip()
    return Narration(
        language=language,
        intro=intro,
        outro_disassemble=outro_disassemble.strip(),
        outro_assemble=outro_assemble.strip(),
        steps=lines,
    )


def run(job_dir: Path, settings: Settings, client: MetaClient | None = None) -> Narration:
    """Ask Spark for the film script and save it as narration.json."""
    plan = artifacts.load(job_dir, Plan)
    identity = artifacts.load_optional(job_dir, Identity)
    safety = artifacts.load_optional(job_dir, Safety)
    reassembly = build_reassembly(plan.steps)
    prompt = build_prompt(plan, identity, safety, reassembly)
    if client is None:
        client = make_client(settings, job_dir=job_dir)
    try:
        data = spark.ask_json(
            client,
            settings,
            name="film_narration",
            schema=NARRATION_JSON_SCHEMA,
            prompt=prompt,
            raw_path=job_dir / "narrate_raw.txt",
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
    except spark.SparkAnswerError as exc:
        raise NarrateError("Spark returned an invalid narration") from exc
    narration = apply_rules(plan, data, (identity.language if identity else "") or "en", safety)
    artifacts.save(job_dir, narration)
    return narration
