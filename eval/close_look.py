"""Try the close look on a few steps of a finished job, on a copy, and save the photos to check.

python -m eval.close_look data/jobs/<id> 3 4 8           # no Meta call: shows the plan
python -m eval.close_look data/jobs/<id> 3 4 8 --real    # spends credits
"""

import shutil
import sys
from pathlib import Path

from app import artifacts
from app.config import get_settings
from app.meta_client import make_client
from app.pipeline import perception
from app.schemas import Plan, StepPerception

KEEP = ("video.mp4", "plan.json", "ingest.json", "identity.json", "transcript.json", "frames.json")


def main(argv: list[str]) -> int:
    real = "--real" in argv
    args = [a for a in argv if a != "--real"]
    if len(args) < 2:
        print(__doc__)
        return 2
    source, wanted = Path(args[0]).resolve(), {int(a) for a in args[1:]}
    plan = artifacts.load(source, Plan)
    steps = [step for step in plan.steps if step.index in wanted]
    if not real:
        for step in steps:
            print(step.index, step.title, step.target_part, step.screws)
        return 0
    copy = source.parent.parent / "close_look" / source.name
    shutil.rmtree(copy, ignore_errors=True)
    (copy / "steps").mkdir(parents=True)
    for name in KEEP:
        if (source / name).exists():
            shutil.copy(source / name, copy / name)
    if (source / "stills").is_dir():
        shutil.copytree(source / "stills", copy / "stills")
    settings = get_settings()
    client = perception.Counted(make_client(settings, job_dir=copy))
    number = 1
    for step in steps:
        sp = StepPerception(index=step.index)
        number = perception.process_one(copy, settings, client, plan, step, sp, number)
        print(step.index, sp.part, [r.box for r in sp.removed], sp.notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
