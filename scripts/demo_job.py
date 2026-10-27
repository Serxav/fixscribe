"""Build a demo job with the real pipeline but a fake Meta client (costs nothing).

Usage: .venv/bin/python scripts/demo_job.py
Prints the job id; open http://localhost:8000/guides/<id> to see the guide.
Useful to work on the web pages without spending credits.
"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from app.config import get_settings
from app.jobs import create_job
from app.meta_client import set_client_factory
from app.pipeline.runner import run_job

SECONDS = 36

TURNS = [
    (1.0, "Step one, remove the two pentalobe screws at the bottom"),
    (7.0, "Step two, open the screen with the suction cup"),
    (13.0, "Paso tres, quita la tapa del conector de la batería"),
    (19.0, "Step four, disconnect the battery"),
    (25.0, "Step five, peel the adhesive strips and lift the battery"),
]


def step(title, instruction, start, end, action, removes, screws=0, warnings=(), conf=0.9):
    return {
        "title": title,
        "instruction": instruction,
        "start_s": start,
        "end_s": end,
        "target_part": removes[0] if removes else "",
        "action": action,
        "removes": list(removes),
        "screw_count": screws,
        "warnings": list(warnings),
        "evidence": [{"t_s": (start + end) / 2, "source": "video", "text": title}],
        "confidence": conf,
    }


ANALYSIS = {
    "title": "Replace the battery",
    "device": "iPhone 12",
    "summary": "Open the phone from the bottom edge, disconnect the battery and lift it out.",
    "difficulty": "medium",
    "estimated_minutes": 25,
    "tools": ["P2 pentalobe", "Tri-point Y000", "Suction cup", "Opening pick", "Spudger"],
    "parts": ["display", "battery connector bracket", "battery"],
    "warnings": [
        "Discharge the battery below 25 % before you start: "
        "a charged lithium battery can catch fire if punctured."
    ],
    "steps": [
        step(
            "Remove the bottom screws",
            "Remove the two pentalobe screws next to the charging port.",
            1.0,
            7.0,
            "unscrew",
            ["bottom screws"],
            screws=2,
        ),
        step(
            "Open the screen",
            "Lift the screen with the suction cup and slide a pick along the edge.",
            7.0,
            13.0,
            "pry",
            ["display"],
            warnings=[
                "Do not insert the pick deeper than 3 mm: the display cables are close to the edge."
            ],
        ),
        step(
            "Remove the connector bracket",
            "Unscrew the bracket over the battery connector and lift it off.",
            13.0,
            19.0,
            "unscrew",
            ["battery connector bracket"],
            screws=3,
        ),
        step(
            "Disconnect the battery",
            "Pry the battery connector straight up with a spudger.",
            19.0,
            25.0,
            "disconnect",
            ["battery connector"],
            warnings=["Use a plastic tool only: metal can short the battery."],
        ),
        step(
            "Lift out the battery",
            "Pull the adhesive strips slowly at a low angle, then lift the battery out.",
            25.0,
            35.0,
            "remove",
            ["battery"],
            warnings=["Never bend or puncture the battery."],
            conf=0.45,
        ),
    ],
}


IDENTITY = {
    "object_name": "smartphone",
    "category": "electronics",
    "brand": "",
    "model": "",
    "task": "repair",
    "problem": "battery replacement",
    "hazards": ["lithium_battery", "sharp_edges"],
    "skill": "intermediate",
    "language": "en",
    "evidence": ["offline demo answer"],
    "confidence": 0.5,
}


class FakeMeta:
    def __init__(self, settings, **kwargs):
        pass

    def transcribe(self, wav, **kwargs):
        turns = [
            {
                "turnId": i,
                "startMs": int(t * 1000),
                "endMs": int(t * 1000) + 2500,
                "transcript": text,
            }
            for i, (t, text) in enumerate(TURNS)
        ]
        return {
            "sessionId": "demo",
            "transcript": "",
            "audioDurationMs": SECONDS * 1000,
            "turns": turns,
        }

    def upload_file(self, path):
        return "file-demo"

    def respond(self, **kwargs):
        # Pass 2 answers "not sure" (confidence 0), so the plan keeps the first analysis.
        unsure = {"start_s": 0, "end_s": 0, "instruction": "", "action": "other", "removes": []}
        unsure |= {"screw_count": 0, "warnings": [], "confidence": 0}
        answers = {"repair_analysis": ANALYSIS, "repair_identity": IDENTITY, "refined_step": unsure}
        name = kwargs["text"]["format"]["name"]
        if name not in answers:
            raise RuntimeError(f"the offline demo has no answer for {name}")
        return SimpleNamespace(output_text=json.dumps(answers[name]))

    def delete_file(self, file_id):
        pass

    def segment(self, image_path, concept, max_side=1280):
        return [], (100, 100)


def main() -> int:
    settings = get_settings()
    jobs_dir = settings.data_dir / "jobs"
    job_id = create_job(jobs_dir).job_id
    original = Path(jobs_dir / job_id / "original.mp4")
    # A moving test pattern with a tone: portrait, like a phone video.
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc2=size=1080x1920:rate=30:duration={SECONDS}",
            "-f", "lavfi", "-i", f"sine=frequency=330:duration={SECONDS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(original),
        ],
        check=True,
    )  # fmt: skip
    set_client_factory(FakeMeta)  # one switch: no stage can reach the real Meta API
    status = run_job(job_id, settings, jobs_dir=jobs_dir)
    print(f"job {job_id}: {status.state} {status.error or ''}".rstrip())
    if status.state == "done":
        # The home page shows this guide as the example.
        (settings.data_dir / "example_job.txt").write_text(job_id)
    print(f"open http://localhost:8000/guides/{job_id}")
    return 0 if status.state == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
