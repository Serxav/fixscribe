"""Review learn-stage suggestions and apply them to domain profiles.

Usage:
    python scripts/review_profiles.py list [--jobs data/jobs]
    python scripts/review_profiles.py apply <job_id> [--only parts,tools]
        [--domains domains] [--jobs data/jobs] [--allow-generic]

`list` groups every job's suggestions by category and shows, for each term, how many
jobs suggested it. `apply` adds one job's suggestions to its category profile file,
respecting the DomainProfile limits (parts 20, tools 12, fasteners 8).
"""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from app import artifacts
from app.domains import DomainProfile
from app.pipeline.learn import normalize_term
from app.schemas import ProfileSuggestions

FIELDS = ("parts", "tools", "fasteners")
LIMITS = {"parts": 20, "tools": 12, "fasteners": 8}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review learn-stage profile suggestions.")
    sub = parser.add_subparsers(dest="command", required=True)
    listed = sub.add_parser("list", help="group suggestions by category with counts")
    listed.add_argument("--jobs", default="data/jobs")
    applied = sub.add_parser("apply", help="add one job's suggestions to its profile file")
    applied.add_argument("job_id")
    applied.add_argument(
        "--only", default=None, help="comma-separated subset of parts,tools,fasteners"
    )
    applied.add_argument("--domains", default="domains")
    applied.add_argument("--jobs", default="data/jobs")
    applied.add_argument("--allow-generic", action="store_true")
    return parser


def cmd_list(args: argparse.Namespace) -> int:
    grouped: dict[str, dict[tuple[str, str], set[str]]] = {}
    jobs_dir = Path(args.jobs)
    if jobs_dir.is_dir():
        for job_dir in sorted(p for p in jobs_dir.iterdir() if p.is_dir()):
            path = job_dir / ProfileSuggestions.FILENAME
            if not path.is_file():
                continue
            try:
                found = ProfileSuggestions.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, ValidationError) as exc:
                print(f"skip {job_dir.name}: {exc}")
                continue
            by_term = grouped.setdefault(found.category, {})
            for item in found.suggestions:
                by_term.setdefault((item.field, item.value), set()).add(job_dir.name)
    if not grouped:
        print("no suggestions found")
        return 0
    for category in sorted(grouped):
        by_term = grouped[category]
        jobs = {job for suggesters in by_term.values() for job in suggesters}
        print(f"{category}: {len(jobs)} job(s) with suggestions")
        for field, value in sorted(by_term):
            print(f"  {field} {value!r}: {len(by_term[(field, value)])} job(s)")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    only = list(FIELDS)
    if args.only is not None:
        only = [item.strip() for item in args.only.split(",") if item.strip()]
        unknown = [item for item in only if item not in FIELDS]
        if unknown:
            print(f"unknown fields: {', '.join(unknown)} (use parts,tools,fasteners)")
            return 2
    path = Path(args.jobs) / args.job_id / ProfileSuggestions.FILENAME
    if not path.is_file():
        print(f"no suggestions for job {args.job_id}")
        return 1
    try:
        found = ProfileSuggestions.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError) as exc:
        print(f"cannot read suggestions for job {args.job_id}: {exc}")
        return 1
    if found.category == "generic" and not args.allow_generic:
        print("refusing to update the generic profile (use --allow-generic to allow it)")
        return 1
    profile_path = Path(args.domains) / f"{found.category}.json"
    if not profile_path.is_file():
        print(f"no domain file for category {found.category!r}")
        return 1
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        DomainProfile.model_validate(data)
    except (OSError, ValueError, ValidationError) as exc:
        print(f"cannot use {profile_path.name}: {exc}")
        return 1
    added: list[str] = []
    skipped: list[str] = []
    for field in FIELDS:
        if field not in only:
            continue
        current = list(data.get(field, []))
        known = {normalize_term(item) for item in current if isinstance(item, str)}
        for item in found.suggestions:
            if item.field != field or normalize_term(item.value) in known:
                continue
            if len(current) >= LIMITS[field]:
                skipped.append(f"{field} {item.value!r}")
                continue
            current.append(item.value)
            known.add(normalize_term(item.value))
            added.append(f"{field} {item.value!r}")
        data[field] = current
    try:
        DomainProfile.model_validate(data)
    except ValidationError as exc:
        print(f"not writing: the merged profile is invalid: {exc}")
        return 1
    artifacts.write_json_atomic(profile_path, data)
    for line in added:
        print(f"added {line}")
    for line in skipped:
        print(f"skipped (over the limit) {line}")
    if not added and not skipped:
        print("nothing new to add: the profile already knows every suggestion")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "apply":
        return cmd_apply(args)
    if args.command == "list":
        return cmd_list(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
