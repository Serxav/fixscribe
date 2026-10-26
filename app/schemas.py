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
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    review: Literal["auto", "needs_review", "edited"] = "auto"

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


# The same model under the name the universal pipeline uses. `screws` stays for compatibility.
FastenerMap = ScrewMap


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
