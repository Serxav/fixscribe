"""Guide and Step models shared by the pipeline, the web app and the export."""

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Box(Strict):
    """A box in normalized image coordinates (0..1), with its number on the screw map."""

    number: int = Field(ge=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def inside_image(self) -> "Box":
        if self.x + self.w > 1 or self.y + self.h > 1:
            raise ValueError("box goes outside the image")
        return self


class ScrewMap(Strict):
    """Fasteners removed in a step: screws by default, or bolts, clips, nuts... (see `kind`)."""

    count: int = Field(ge=0)
    boxes: list[Box] = Field(default_factory=list)
    kind: str = "screw"  # the fastener type, as named by the domain profile

    @model_validator(mode="after")
    def unique_numbers(self) -> "ScrewMap":
        numbers = [box.number for box in self.boxes]
        if len(numbers) != len(set(numbers)):
            raise ValueError("screw numbers must be unique")
        return self


class Evidence(Strict):
    """A moment in the video that supports what the step says."""

    t_s: float = Field(ge=0)
    source: Literal["video", "audio"]
    text: str


class Step(Strict):
    index: int = Field(ge=1)
    title: str
    instruction: str
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    keyframe_s: float | None = None
    target_part: str | None = None
    action: str | None = None
    removes: list[str] = Field(default_factory=list)
    depends_on: list[int] = Field(default_factory=list)
    screws: ScrewMap | None = None
    clip: str | None = None
    image: str | None = None
    overlay: str | None = None
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    motion: "StepMotion | None" = None  # SAM-tracked cinematic clip and part cut-out (motion stage)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    review: Literal["auto", "needs_review", "edited"] = "auto"
    # Spark's draft number in time order: the index fusion.json and refine.json use for this
    # step. It differs from `index` when the plan drops or reorders steps.
    source_index: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def check_seconds(self) -> "Step":
        if self.end_s <= self.start_s:
            raise ValueError("end_s must be after start_s")
        if self.keyframe_s is not None and not self.start_s <= self.keyframe_s <= self.end_s:
            raise ValueError("keyframe_s must be between start_s and end_s")
        if any(dep >= self.index for dep in self.depends_on):
            raise ValueError("a step can only depend on earlier steps")
        return self


class ReassemblyStep(Strict):
    index: int = Field(ge=1)
    source_step: int = Field(ge=1)
    action: str
    instruction: str
    parts: list[str] = Field(default_factory=list)
    screws: ScrewMap | None = None
    warnings: list[str] = Field(default_factory=list)


class InspectorEntry(Strict):
    step_index: int = Field(ge=1)
    tool: Literal["segment", "set_keyframe", "update_step"]
    args: dict[str, Any] = Field(default_factory=dict)
    result: str = ""


class Guide(Strict):
    FILENAME: ClassVar[str] = "guide.json"

    title: str
    device: str
    summary: str = ""
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    estimated_minutes: int = Field(default=0, ge=0)
    mode: Literal["narrated", "silent"]
    language: str = "en"
    duration_s: float | None = Field(default=None, gt=0)
    tools: list[str] = Field(default_factory=list)
    parts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    reassembly: list[ReassemblyStep] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)  # automatic checks, e.g. the screw check
    inspector_log: list[InspectorEntry] = Field(default_factory=list)
    identity: "Identity | None" = None  # what the video shows (identify stage)
    safety: "Safety | None" = None  # rules-first safety decision (safety stage)
    proof: "Proof | None" = None  # where every claim of the guide comes from (proof stage)
    narration: "Narration | None" = None  # spoken script of the repair film (narrate stage)

    @model_validator(mode="after")
    def check_steps(self) -> "Guide":
        if [step.index for step in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("step indexes must be 1, 2, 3, ... in order")
        starts = [step.start_s for step in self.steps]
        if starts != sorted(starts):
            raise ValueError("steps must be ordered by start_s")
        if self.duration_s is not None:
            for step in self.steps:
                if step.end_s > self.duration_s:
                    raise ValueError(f"step {step.index} ends after the video")
        for item in self.reassembly:
            if item.source_step > len(self.steps):
                raise ValueError(f"reassembly step {item.index} points to a missing step")
        return self


class DraftStep(BaseModel):
    """One step as Muse Spark returns it. Lenient: the guide builder cleans it up."""

    model_config = ConfigDict(extra="ignore")

    source_index: int | None = None  # set by the plan, never by Spark (not in the JSON schema)

    title: str
    instruction: str = ""
    start_s: float
    end_s: float
    target_part: str | None = None
    action: str | None = None
    removes: list[str] = Field(default_factory=list)
    screw_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)

    # The strict JSON schema cannot set numeric limits, so Spark may send numbers out of range.
    # We fix them here instead of failing the whole job.
    @field_validator("screw_count", mode="before")
    @classmethod
    def no_negative_screws(cls, value: Any) -> Any:
        return max(0, value) if isinstance(value, int | float) else value

    @field_validator("confidence", mode="before")
    @classmethod
    def confidence_0_to_1(cls, value: Any) -> Any:
        if not isinstance(value, int | float):
            return value
        if 1 < value <= 100:
            value = value / 100  # a percentage, e.g. 85 -> 0.85
        return min(1.0, max(0.0, value))

    @field_validator("evidence", mode="before")
    @classmethod
    def no_negative_evidence_times(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        return [
            item | {"t_s": max(0.0, item["t_s"])}
            if isinstance(item, dict) and isinstance(item.get("t_s"), int | float)
            else item
            for item in value
        ]


class Analysis(BaseModel):
    """The JSON that the analyze stage asks Muse Spark for (saved as analysis.json)."""

    FILENAME: ClassVar[str] = "analysis.json"
    model_config = ConfigDict(extra="ignore")

    title: str = "Repair guide"
    device: str = "Unknown device"
    summary: str = ""
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    estimated_minutes: int = Field(default=0, ge=0)
    tools: list[str] = Field(default_factory=list)
    parts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    steps: list[DraftStep] = Field(default_factory=list)

    @field_validator("estimated_minutes", mode="before")
    @classmethod
    def no_negative_minutes(cls, value: Any) -> Any:
        return max(0, value) if isinstance(value, int | float) else value


ACTIONS = [
    "remove",
    "disconnect",
    "unscrew",
    "unclip",
    "pry",
    "open",
    "peel",
    "inspect",
    "clean",
    "other",
]


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    """A strict JSON Schema object: every key required, no extra keys."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_STRINGS = {"type": "array", "items": {"type": "string"}}

# Sent to Muse Spark as text.format = {"type": "json_schema", "name": "repair_analysis",
# "schema": ANALYSIS_JSON_SCHEMA, "strict": True}. See https://dev.meta.ai/docs/structured-output
# Strict mode needs every key in "required" and additionalProperties false. Its output is then
# validated again with the Analysis model above.
ANALYSIS_JSON_SCHEMA: dict[str, Any] = _object(
    {
        "title": {"type": "string"},
        "device": {"type": "string"},
        "summary": {"type": "string"},
        "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
        "estimated_minutes": {"type": "integer"},
        "tools": _STRINGS,
        "parts": _STRINGS,
        "warnings": _STRINGS,
        "steps": {
            "type": "array",
            "items": _object(
                {
                    "title": {"type": "string"},
                    "instruction": {"type": "string"},
                    "start_s": {"type": "number"},
                    "end_s": {"type": "number"},
                    "target_part": {"type": "string"},
                    "action": {"type": "string", "enum": ACTIONS},
                    "removes": _STRINGS,
                    "screw_count": {"type": "integer"},
                    "warnings": _STRINGS,
                    "evidence": {
                        "type": "array",
                        "items": _object(
                            {
                                "t_s": {"type": "number"},
                                "source": {"type": "string", "enum": ["video", "audio"]},
                                "text": {"type": "string"},
                            }
                        ),
                    },
                    "confidence": {"type": "number"},
                }
            ),
        },
    }
)


# --- Job artifacts --------------------------------------------------------------------------
# Every file a pipeline stage writes has a model here, with its file name. Stages read and write
# them only through app/artifacts.py. Each stage owns exactly one artifact.


class SourceVideo(Strict):
    """What the uploaded file really is (before any conversion)."""

    filename: str
    width: int = Field(gt=0)  # display size, after the rotation tag
    height: int = Field(gt=0)
    rotation: int = 0
    fps: float = Field(default=0.0, ge=0)
    vfr: bool = False
    codec: str = ""
    pix_fmt: str = ""
    color_transfer: str = ""
    color_primaries: str = ""
    hdr: bool = False
    duration_s: float = Field(gt=0)


class IngestInfo(Strict):
    FILENAME: ClassVar[str] = "ingest.json"

    duration_s: float = Field(gt=0)
    width: int = Field(gt=0)  # of video.mp4, the working proxy
    height: int = Field(gt=0)
    has_audio: bool
    fps: float = Field(default=30.0, gt=0)
    source: SourceVideo | None = None


class Turn(Strict):
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    text: str


class Transcript(Strict):
    FILENAME: ClassVar[str] = "transcript.json"

    mode: Literal["narrated", "silent"]
    duration_s: float = Field(default=0.0, ge=0)
    transcript: str = ""
    turns: list[Turn] = Field(default_factory=list)


class Segment(Strict):
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)


class Scenes(Strict):
    FILENAME: ClassVar[str] = "scenes.json"

    source: Literal["voice", "none"]
    cuts: list[float] = Field(default_factory=list)
    # The whole spoken turn that contains each cut word: the word is somewhere inside it.
    cut_intervals: list[Segment] = Field(default_factory=list)
    segments: list[Segment] = Field(default_factory=list)


class Candidate(Strict):
    t: float = Field(ge=0)
    kind: Literal["pause", "scene"]
    score: float = Field(ge=0, le=1)


class Signals(Strict):
    FILENAME: ClassVar[str] = "signals.json"

    fps: float = Field(gt=0)
    duration_s: float = Field(ge=0)
    motion: list[list[float]] = Field(default_factory=list)  # [t, energy]
    scene: list[list[float]] = Field(default_factory=list)  # [t, score]
    candidates: list[Candidate] = Field(default_factory=list)


class FusionStep(Strict):
    index: int = Field(ge=1)
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    start_source: Literal["voice", "pause", "scene", "spark"]
    end_source: Literal["voice", "pause", "scene", "spark"]
    start_shift_s: float = 0.0
    end_shift_s: float = 0.0
    agreement: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)


class Fusion(Strict):
    """Step boundaries after snapping Spark's times to voice and visual evidence."""

    FILENAME: ClassVar[str] = "fusion.json"

    candidates: int = Field(default=0, ge=0)
    steps: list[FusionStep] = Field(default_factory=list)


class Plan(Strict):
    """Final steps and times, before media: written by the plan stage."""

    FILENAME: ClassVar[str] = "plan.json"

    title: str
    device: str
    summary: str = ""
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    estimated_minutes: int = Field(default=0, ge=0)
    mode: Literal["narrated", "silent"]
    duration_s: float = Field(gt=0)
    tools: list[str] = Field(default_factory=list)
    parts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)


class StepMedia(Strict):
    index: int = Field(ge=1)
    keyframe_s: float = Field(ge=0)
    image: str  # display JPEG (long side <= 1600 px)
    clip: str | None = None
    still: str | None = None  # native-resolution PNG from the original, for SAM


class NormBox(Strict):
    """A box in normalized image coordinates (0..1) of the still it was found on."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class ScrewRecord(Strict):
    """One screw that was there before the step and gone after it."""

    id: str  # "S1", "S2"... unique in the guide
    number: int = Field(ge=1)  # 1.. within its step, in reading order
    box: NormBox  # on the step's keyframe still
    confidence: float | None = Field(default=None, ge=0, le=1)


class PartHighlight(Strict):
    concept: str
    box: NormBox
    confidence: float | None = Field(default=None, ge=0, le=1)


class StepPerception(Strict):
    index: int = Field(ge=1)
    part: PartHighlight | None = None
    screws_before: int = Field(default=0, ge=0)
    screws_after: int = Field(default=0, ge=0)
    removed: list[ScrewRecord] = Field(default_factory=list)
    overlay: str | None = None  # display JPEG with the part and the numbered screws
    sam_calls: int = Field(default=0, ge=0)
    notes: list[str] = Field(default_factory=list)


class Perception(Strict):
    """What SAM 3.1 found on the stills: the part to touch and the screw ledger."""

    FILENAME: ClassVar[str] = "perception.json"

    steps: list[StepPerception] = Field(default_factory=list)
    sam_calls: int = Field(default=0, ge=0)


class Frames(Strict):
    FILENAME: ClassVar[str] = "frames.json"

    steps: list[StepMedia] = Field(default_factory=list)


class StageRecord(Strict):
    status: Literal["done", "failed", "skipped"]
    version: str
    started_at: str
    seconds: float = Field(ge=0)
    usd: float = Field(default=0.0, ge=0)
    error: str | None = None


class Manifest(Strict):
    """How this job was produced: one record per stage, in order."""

    FILENAME: ClassVar[str] = "manifest.json"

    stages: dict[str, StageRecord] = Field(default_factory=dict)
    total_seconds: float = Field(default=0.0, ge=0)
    total_usd: float = Field(default=0.0, ge=0)


class RefinedStep(Strict):
    """One uncertain step looked at again by Spark on a short clip with a burned-in timecode."""

    index: int = Field(ge=1)  # the step number in Spark's time order (same as fusion)
    start_s: float = Field(ge=0)  # absolute seconds in the video (read from the timecode)
    end_s: float = Field(ge=0)
    instruction: str
    action: str
    removes: list[str] = Field(default_factory=list)
    screw_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class Refine(Strict):
    FILENAME: ClassVar[str] = "refine.json"

    steps: list[RefinedStep] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)  # why a selected step was not refined


# Sent as text.format for the refine pass (strict: every key required, no extra keys).
REFINE_JSON_SCHEMA: dict[str, Any] = _object(
    {
        "start_s": {"type": "number"},
        "end_s": {"type": "number"},
        "instruction": {"type": "string"},
        "action": {"type": "string", "enum": ACTIONS},
        "removes": _STRINGS,
        "screw_count": {"type": "integer"},
        "warnings": _STRINGS,
        "confidence": {"type": "number"},
    }
)


# --- Universal repair: what is it, and is it safe? ---------------------------------------------

CATEGORIES = [
    "electronics",
    "appliance",
    "furniture",
    "automotive",
    "plumbing",
    "electrical",
    "tools",
    "other",
]

HAZARDS = [
    "mains_voltage",
    "gas",
    "pressurized_water",
    "refrigerant",
    "high_voltage_battery",
    "lithium_battery",
    "airbag",
    "raised_vehicle",
    "heavy_part",
    "sharp_edges",
    "hot_surface",
    "spring_tension",
    "chemicals",
]

TASKS = ["disassemble", "repair", "maintain", "assemble", "diagnose", "other"]


class Identity(Strict):
    """What FixScribe is looking at, decided before anything else (identify stage)."""

    FILENAME: ClassVar[str] = "identity.json"

    object_name: str  # "front-loading washing machine", "iPhone 12", "office chair"
    category: Literal[
        "electronics", "appliance", "furniture", "automotive", "plumbing", "electrical",
        "tools", "other",
    ]  # fmt: skip
    brand: str = ""
    model: str = ""
    task: Literal["disassemble", "repair", "maintain", "assemble", "diagnose", "other"]
    problem: str = ""  # what seems wrong, if anything ("drum does not spin")
    hazards: list[
        Literal[
            "mains_voltage", "gas", "pressurized_water", "refrigerant", "high_voltage_battery",
            "lithium_battery", "airbag", "raised_vehicle", "heavy_part", "sharp_edges",
            "hot_surface", "spring_tension", "chemicals",
        ]
    ] = Field(default_factory=list)  # fmt: skip
    skill: Literal["beginner", "intermediate", "expert"] = "intermediate"
    language: str = "en"  # language the technician speaks, ISO 639-1
    evidence: list[str] = Field(default_factory=list)  # what in the images or speech decided it
    confidence: float = Field(default=0.5, ge=0, le=1)

    @field_validator("confidence", mode="before")
    @classmethod
    def confidence_0_to_1(cls, value: Any) -> Any:
        return DraftStep.confidence_0_to_1(value)


IDENTITY_JSON_SCHEMA: dict[str, Any] = _object(
    {
        "object_name": {"type": "string"},
        "category": {"type": "string", "enum": CATEGORIES},
        "brand": {"type": "string"},
        "model": {"type": "string"},
        "task": {"type": "string", "enum": TASKS},
        "problem": {"type": "string"},
        "hazards": {"type": "array", "items": {"type": "string", "enum": HAZARDS}},
        "skill": {"type": "string", "enum": ["beginner", "intermediate", "expert"]},
        "language": {"type": "string"},
        "evidence": _STRINGS,
        "confidence": {"type": "number"},
    }
)


class Safety(Strict):
    """Safety decision for a job. Deterministic rules first; a model may only make it stricter."""

    FILENAME: ClassVar[str] = "safety.json"

    level: Literal["normal", "caution", "professional_only"] = "normal"
    reasons: list[str] = Field(default_factory=list)
    prechecks: list[str] = Field(default_factory=list)  # must be done before step 1
    blocked: list[str] = Field(default_factory=list)  # operations we never give instructions for


# --- Proof mode: every claim of the guide with the evidence behind it --------------------------

CLAIM_STATUS = ["verified", "supported", "unverified"]


class Claim(Strict):
    """One thing a step says, and how sure we are of it.

    verified: two independent sources agree, or a measurement confirms it (SAM, timecode).
    supported: one source says it (Spark saw it, or the technician said it).
    unverified: nothing backs it; the guide shows it with a warning.
    """

    field: Literal["boundaries", "instruction", "fastener_count", "part"]
    status: Literal["verified", "supported", "unverified"]
    sources: list[str] = Field(default_factory=list)  # "voice 12.4 s: 'quita los tornillos'"


class StepProof(Strict):
    index: int = Field(ge=1)
    claims: list[Claim] = Field(default_factory=list)
    score: float = Field(default=0.0, ge=0, le=1)  # verified = 1, supported = 0.5, unverified = 0


class Proof(Strict):
    FILENAME: ClassVar[str] = "proof.json"

    steps: list[StepProof] = Field(default_factory=list)
    score: float = Field(default=0.0, ge=0, le=1)  # mean of the step scores


# --- Self-growing domain profiles ---------------------------------------------------------------


class ProfileSuggestion(Strict):
    field: Literal["parts", "fasteners", "tools"]
    value: str  # lower case, as it would go in domains/<category>.json
    seen_in: str  # where it came from: "step 3: Remove the drain pump"


class ProfileSuggestions(Strict):
    """New vocabulary this job found that its domain profile does not have yet (human review)."""

    FILENAME: ClassVar[str] = "profile_suggestions.json"

    category: str  # profile the suggestions are for ("generic" when the category is unknown)
    object_name: str = ""
    suggestions: list[ProfileSuggestion] = Field(default_factory=list)


# --- Ghost camera: is this step done on the user's own object? ---------------------------------


class StepCheck(Strict):
    """The answer to a photo the user takes after doing one step of a guide."""

    step: int = Field(ge=1)
    verdict: Literal["done", "not_yet", "unclear"]
    message: str  # shown to the user: "2 bolts are still in place (top left)."
    fastener_kind: str = "screw"
    expected_left: int | None = Field(default=None, ge=0)  # fasteners still there after the step
    found: int | None = Field(default=None, ge=0)  # fasteners SAM found on the photo
    boxes: list[NormBox] = Field(default_factory=list)  # where, on the user's photo
    aligned: bool = False  # the photo was matched to the guide's still
    sam_calls: int = Field(default=0, ge=0)


# --- Compare my attempt: a user's own repair video against a guide -----------------------------

ATTEMPT_STATUS = ["done", "skipped", "different", "unclear"]


class AttemptStep(Strict):
    ref_step: int = Field(ge=1)  # step index in the reference guide
    status: Literal["done", "skipped", "different", "unclear"]
    t_s: float | None = Field(default=None, ge=0)  # where it happens in the attempt video
    fasteners_seen: int | None = Field(default=None, ge=0)
    note: str = ""  # "Removed 3 bolts; the guide removes 4."

    @field_validator("t_s", "fasteners_seen", mode="before")
    @classmethod
    def negative_means_unknown(cls, value: Any) -> Any:
        return None if isinstance(value, int | float) and value < 0 else value


class AttemptReview(Strict):
    FILENAME: ClassVar[str] = "attempt_review.json"

    guide_job: str  # job id of the reference guide
    steps: list[AttemptStep] = Field(default_factory=list)
    order_ok: bool = True  # computed by rules, not by the model
    safety_issues: list[str] = Field(default_factory=list)  # computed by rules from skipped steps
    summary: str = ""
    score: float = Field(default=0.0, ge=0, le=1)  # share of steps "done"


# Sent to Muse Spark as text.format json_schema "attempt_review". Rules fill the other fields.
ATTEMPT_JSON_SCHEMA: dict[str, Any] = _object(
    {
        "steps": {
            "type": "array",
            "items": _object(
                {
                    "ref_step": {"type": "integer"},
                    "status": {"type": "string", "enum": ATTEMPT_STATUS},
                    "t_s": {"type": "number"},  # -1 when not seen
                    "fasteners_seen": {"type": "integer"},  # -1 when not counted
                    "note": {"type": "string"},
                }
            ),
        },
        "summary": {"type": "string"},
    }
)


# --- SAM Motion: the step clip with the part and fasteners tracked by SAM 3.1 -------------------


class StepMotion(Strict):
    """What the motion stage made for one step (paths are relative to the job folder)."""

    index: int = Field(ge=1)
    clip: str  # cinematic clip: part lit and outlined, fasteners ringed and numbered
    clip_reverse: str | None = None  # the same clip played backwards, for the assembly film
    cutout: str | None = None  # PNG with transparency: the part alone, cut along its SAM mask
    cutout_box: NormBox | None = None  # where the cut-out sits on the step frame
    outline: str = ""  # SVG path of the part outline in a 0..1000 x 0..1000 box of the frame
    part: str = ""  # the concept SAM tracked ("back cover")
    fasteners_tracked: int = Field(default=0, ge=0)  # distinct fastener ids SAM followed
    frames: int = Field(default=0, ge=0)  # frames sent to SAM (billing)
    start_s: float = Field(default=0.0, ge=0)  # where the clip starts in the video
    end_s: float = Field(default=0.0, ge=0)
    voice: bool = False  # the clip carries the technician's own narration for this moment


class Motion(Strict):
    FILENAME: ClassVar[str] = "motion.json"

    steps: list[StepMotion] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# --- Narration: the spoken script of the repair film --------------------------------------------


class NarrationLine(Strict):
    index: int = Field(ge=1)  # the guide step
    disassemble: str  # what the voice says while this step's clip plays (taking apart)
    assemble: str  # what it says when the same step is played backwards (putting back)


class Narration(Strict):
    """Written by Spark in the technician's language; spoken by the viewer's device."""

    FILENAME: ClassVar[str] = "narration.json"

    language: str = "en"  # BCP 47 / ISO 639-1, used to pick the device voice
    intro: str
    outro_disassemble: str
    outro_assemble: str
    steps: list[NarrationLine] = Field(default_factory=list)


NARRATION_JSON_SCHEMA: dict[str, Any] = _object(
    {
        "intro": {"type": "string"},
        "outro_disassemble": {"type": "string"},
        "outro_assemble": {"type": "string"},
        "steps": {
            "type": "array",
            "items": _object(
                {
                    "index": {"type": "integer"},
                    "disassemble": {"type": "string"},
                    "assemble": {"type": "string"},
                }
            ),
        },
    }
)


Guide.model_rebuild()  # Identity, Safety, Proof, StepMotion and Narration are defined after Guide
Step.model_rebuild()
