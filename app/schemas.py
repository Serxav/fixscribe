"""Guide and Step models shared by the pipeline, the web app and the export."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    count: int = Field(ge=0)
    boxes: list[Box] = Field(default_factory=list)

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
