"""Suggest new domain vocabulary from a finished guide (profile_suggestions.json).

Deterministic, no Meta call: after guide.json exists, this stage lists the parts,
fasteners and tools the job used that its domain profile does not know yet. Nothing is
added automatically; a human reviews the suggestions with scripts/review_profiles.py.
"""

import re
from pathlib import Path
from typing import Any

from app import artifacts
from app.domains import DomainProfile, profile_for
from app.schemas import Guide, Identity, ProfileSuggestion, ProfileSuggestions

VERSION = "1"
ARTICLES = ("a", "an", "the")


def normalize_term(text: str) -> str:
    """Lower case, collapse spaces, drop one leading article, simple singular."""
    term = re.sub(r"\s+", " ", text.lower().strip())
    words = term.split(" ")
    if words and words[0] in ARTICLES:
        term = " ".join(words[1:])
    if len(term) > 3 and term.endswith("s") and not term.endswith("ss"):
        term = term[:-1]
    return term


def _known_terms(profile: DomainProfile) -> dict[str, set[str]]:
    return {
        "parts": {normalize_term(item) for item in profile.parts},
        "tools": {normalize_term(item) for item in profile.tools},
        "fasteners": {normalize_term(item) for item in profile.fasteners},
    }


def suggest(guide: Guide, profile: DomainProfile) -> list[ProfileSuggestion]:
    """New vocabulary the guide uses that the profile does not know yet."""
    known = _known_terms(profile)
    out: list[ProfileSuggestion] = []
    seen: set[tuple[str, str]] = set()

    def add(field: str, raw: str | None, seen_in: str) -> None:
        if not raw:
            return
        value = normalize_term(raw)
        if len(value) < 3 or len(value) > 40:
            return
        if value in known[field] or (field, value) in seen:
            return
        seen.add((field, value))
        out.append(ProfileSuggestion(field=field, value=value, seen_in=seen_in))

    for part in guide.parts:
        add("parts", part, "guide parts")
    for step in guide.steps:
        label = f"step {step.index}: {step.title}"
        add("parts", step.target_part, label)
        for removed in step.removes:
            add("parts", removed, label)
    for tool in guide.tools:
        add("tools", tool, "guide tools")
    for step in guide.steps:
        if step.screws and step.screws.kind:
            add("fasteners", step.screws.kind, f"step {step.index}: {step.title}")
    return out


def run(job_dir: Path, settings: Any) -> ProfileSuggestions:
    """Write profile_suggestions.json for the guide in job_dir."""
    guide = artifacts.load(job_dir, Guide)
    identity = artifacts.load_optional(job_dir, Identity)
    if identity is not None and identity.category != "other":
        category, object_name = identity.category, identity.object_name
    else:
        category = "generic"
        object_name = identity.object_name if identity is not None else ""
    result = ProfileSuggestions(
        category=category,
        object_name=object_name,
        suggestions=suggest(guide, profile_for(category)),
    )
    artifacts.save(job_dir, result)
    return result
