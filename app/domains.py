"""Domain profiles: one JSON file per repair category in domains/."""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.schemas import HAZARDS

DOMAINS_DIR = Path(__file__).resolve().parents[1] / "domains"


class DomainError(Exception):
    """A domain JSON file is missing, unreadable or invalid."""


class DomainProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    label: str
    fasteners: list[str] = Field(min_length=2, max_length=8)
    fastener_kind: str
    parts: list[str] = Field(min_length=5, max_length=20)
    tools: list[str] = Field(min_length=3, max_length=12)
    prechecks: list[str] = Field(min_length=1)
    default_hazards: list[str] = Field(default_factory=list)
    prompt_hint: str = Field(min_length=1, max_length=400)

    @field_validator("category", "label", "fastener_kind")
    @classmethod
    def no_blanks(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("fasteners")
    @classmethod
    def sane_fasteners(cls, items: list[str]) -> list[str]:
        if len(set(items)) != len(items):
            raise ValueError("fasteners must be unique")
        for item in items:
            if not item.strip() or item != item.lower():
                raise ValueError("fasteners must be lower case nouns")
        return items

    @field_validator("prechecks")
    @classmethod
    def short_prechecks(cls, items: list[str]) -> list[str]:
        for item in items:
            if not item.strip() or len(item) >= 100:
                raise ValueError("each precheck must be 1..99 chars")
        return items

    @field_validator("default_hazards")
    @classmethod
    def known_hazards(cls, items: list[str]) -> list[str]:
        for item in items:
            if item not in HAZARDS:
                raise ValueError(f"unknown hazard: {item!r}")
        return items

    @field_validator("prompt_hint")
    @classmethod
    def short_hint(cls, value: str) -> str:
        sentences = [s for s in value.replace("?", ".").replace("!", ".").split(".") if s.strip()]
        if not 1 <= len(sentences) <= 3:
            raise ValueError("prompt_hint must be 1-3 sentences")
        return value

    @model_validator(mode="after")
    def kind_matches_fasteners(self) -> "DomainProfile":
        words = {word for item in self.fasteners for word in item.split()}
        if self.fastener_kind not in self.fasteners and self.fastener_kind not in words:
            raise ValueError("fastener_kind must be a fastener or one of its words")
        return self


def load_profile(path: Path) -> DomainProfile:
    """Load and validate one domain file. The category must match the file stem."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DomainError(f"{path.name}: cannot read domain file: {exc}") from exc
    try:
        profile = DomainProfile.model_validate(data)
    except ValidationError as exc:
        raise DomainError(f"{path.name}: invalid domain profile: {exc}") from exc
    if profile.category != path.stem:
        raise DomainError(f"{path.name}: category {profile.category!r} must match file stem")
    return profile


def _load_all(domains_dir: Path) -> dict[str, DomainProfile]:
    return {path.stem: load_profile(path) for path in sorted(Path(domains_dir).glob("*.json"))}


@lru_cache(maxsize=1)
def _cached_default() -> dict[str, DomainProfile]:
    return _load_all(DOMAINS_DIR)


def all_profiles(domains_dir: Path = DOMAINS_DIR) -> dict[str, DomainProfile]:
    """All profiles by category. The default directory is read once and cached."""
    if Path(domains_dir) == DOMAINS_DIR:
        return _cached_default()
    return _load_all(Path(domains_dir))


def profile_for(category: str | None, domains_dir: Path = DOMAINS_DIR) -> DomainProfile:
    """Exact category match, else the generic fallback. Never raises for unknown input."""
    profiles = all_profiles(domains_dir)
    if category is not None and category != "other" and category in profiles:
        return profiles[category]
    return profiles["generic"]
