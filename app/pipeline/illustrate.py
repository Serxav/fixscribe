"""Illustrate stage: Muse Image draws an exploded-view illustration per step.

Only steps that remove a part are illustrated (at most MAX_ILLUSTRATIONS): the
step's real keyframe goes in, a clean product-manual exploded view comes out
(the part lifted off, fasteners floating above their holes, numbered). Files
land in ``steps/NN_illustration.webp`` and are listed in illustrations.json.
A refused or failed step is a note, never a crash.
"""

import logging
from pathlib import Path
from typing import ClassVar

from pydantic import Field

from app import artifacts
from app.config import Settings
from app.meta_client import BudgetExceeded, ImagePolicyError, MetaClient, make_client
from app.schemas import Frames, Identity, Plan, Step, Strict
from app.text import plural

logger = logging.getLogger(__name__)

VERSION = "1"
MAX_ILLUSTRATIONS = 4

REMOVE_ACTIONS = frozenset({"remove", "unscrew", "unclip", "pry", "open", "disconnect"})

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "illustrate_v1.md"


class StepIllustration(Strict):
    """One exploded-view illustration of a step."""

    index: int = Field(ge=1)
    image: str
    prompt: str


class Illustrations(Strict):
    """Exploded-view illustrations of the steps that remove a part."""

    FILENAME: ClassVar[str] = "illustrations.json"

    steps: list[StepIllustration] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def wants_illustration(step: Step) -> bool:
    """True for steps that remove a part: a target part plus fasteners or a removal action."""
    if not (step.target_part or "").strip():
        return False
    if step.screws is not None and step.screws.count > 0:
        return True
    return (step.action or "").strip().lower() in REMOVE_ACTIONS


def select_steps(steps: list[Step]) -> list[Step]:
    """Steps to illustrate, in step order, at most MAX_ILLUSTRATIONS."""
    return [step for step in steps if wants_illustration(step)][:MAX_ILLUSTRATIONS]


def describe_fasteners(step: Step) -> str:
    """Fastener summary for the <<FASTENERS>> prompt block ("4 screws", else "none")."""
    screws = step.screws
    if screws is None or screws.count <= 0:
        return "none"
    kind = (screws.kind or "screw").strip() or "screw"
    return f"{screws.count} {plural(kind, screws.count)}"


def build_prompt(object_name: str, step: Step) -> str:
    """Fill the illustrate prompt template for one step."""
    template = PROMPT_PATH.read_text(encoding="utf-8")
    action = (step.action or "").strip() or "remove"
    prompt = template.replace("<<OBJECT>>", object_name)
    prompt = prompt.replace("<<PART>>", (step.target_part or "").strip())
    prompt = prompt.replace("<<FASTENERS>>", describe_fasteners(step))
    return prompt.replace("<<ACTION>>", action)


def object_name(plan: Plan, identity: Identity | None) -> str:
    """The object as the identify stage named it, else the plan device."""
    if identity is not None and identity.object_name:
        return identity.object_name
    return plan.device


def run(job_dir: Path, settings: Settings, client: MetaClient | None = None) -> Illustrations:
    """Draw one exploded view per chosen step and save illustrations.json."""
    plan = artifacts.load(job_dir, Plan)
    identity = artifacts.load_optional(job_dir, Identity)
    frames = artifacts.load_optional(job_dir, Frames)
    media_by_index = {media.index: media.image for media in frames.steps} if frames else {}
    if client is None:
        client = make_client(settings, job_dir=job_dir)
    name = object_name(plan, identity)
    out: list[StepIllustration] = []
    notes: list[str] = []
    for step in select_steps(plan.steps):
        rel = media_by_index.get(step.index) or step.image
        if not rel:
            notes.append(f"step {step.index}: skipped (no keyframe image)")
            continue
        src = job_dir / rel
        if not src.is_file():
            notes.append(f"step {step.index}: skipped (missing {rel})")
            continue
        prompt = build_prompt(name, step)
        try:
            data = client.edit_image(src, prompt)
        except BudgetExceeded:
            notes.append(f"step {step.index}: stopped (budget reached)")
            break
        except ImagePolicyError:
            logger.warning("illustrate: step %d refused by content policy", step.index)
            notes.append(f"step {step.index}: skipped (content policy)")
        except Exception as exc:
            logger.warning("illustrate: step %d failed: %s", step.index, exc)
            notes.append(f"step {step.index}: skipped ({exc})")
        else:
            filename = f"{step.index:02d}_illustration.webp"
            artifacts.write_bytes_atomic(job_dir / "steps" / filename, data)
            out.append(StepIllustration(index=step.index, image=f"steps/{filename}", prompt=prompt))
    result = Illustrations(steps=out, notes=notes)
    artifacts.save(job_dir, result)
    return result
