"""The agent loop: Muse Wonder picks one tool per turn until the guide is filed (in progress)."""

from pathlib import Path


def launch(job_dir: Path, *, resume: bool = False) -> bool:
    """Start (or resume) the agent for a job in the background. False if it is already running."""
    raise NotImplementedError("the agent loop is being built")
