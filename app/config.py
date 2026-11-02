"""Process-wide settings loaded from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """Runtime configuration. Env var name is in brackets in task 001."""

    model_api_key: str = field(default="", repr=False)  # [MODEL_API_KEY]
    meta_api_base: str = "https://api.meta.ai/v1"  # [META_API_BASE]
    spark_model: str = "muse-spark-1.3"  # [SPARK_MODEL]
    wonder_model: str = "muse-wonder-1.0"  # [WONDER_MODEL]
    sam_model: str = "sam-3.1"  # [SAM_MODEL]
    asr_model: str = "muse-voice-transcribe-1.0"  # [ASR_MODEL]
    max_video_seconds: int = 600  # [MAX_VIDEO_SECONDS]
    enable_inspector: bool = True  # [ENABLE_INSPECTOR]
    daily_job_limit: int = 20  # [DAILY_JOB_LIMIT]
    pipeline_workers: int = 4  # [PIPELINE_WORKERS] steps worked on at once in perception and motion
    budget_usd: float = 120.0  # [BUDGET_USD]
    job_budget_usd: float = 2.5  # [JOB_BUDGET_USD]
    agent_budget_usd: float = 1.0  # [AGENT_BUDGET_USD] extra per job for the Muse Wonder agent
    live_budget_usd: float = 2.0  # [LIVE_BUDGET_USD] per job for the live coach, on its own counter
    live_max_calls: int = 300  # [LIVE_MAX_CALLS] per job: a public sample guide needs more
    visitor_videos_per_day: int = 0  # [VISITOR_VIDEOS_PER_DAY] 0 = off: judges may try everything
    visitor_coach_minutes_per_day: int = 0  # [VISITOR_COACH_MINUTES_PER_DAY]
    visitor_questions_per_hour: int = 0  # [VISITOR_QUESTIONS_PER_HOUR] voice and typed
    visitor_actions_per_hour: int = 0  # [VISITOR_ACTIONS_PER_HOUR] step checks, taps, the agent
    trust_proxy: bool = (
        False  # [TRUST_PROXY] true behind the host's proxy: visitors by X-Forwarded-For
    )
    demo_job: str = ""  # [DEMO_JOB] folder under demo/: a read-only sample guide for visitors
    data_dir: Path = Path("data")  # [DATA_DIR]
    voice_model_dir: Path = Path("models/vits-mms-eng")  # [VOICE_MODEL_DIR]

    @property
    def jobs_dir(self) -> Path:
        """The one folder that holds every job (web, runner and scripts all use this)."""
        return self.data_dir / "jobs"


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes")


def get_settings() -> Settings:
    """Read settings from the environment (after loading `.env`)."""
    load_dotenv(override=False)
    env = os.environ

    enable_inspector = True
    if "ENABLE_INSPECTOR" in env:
        enable_inspector = _parse_bool(env["ENABLE_INSPECTOR"])

    data_dir = Path("data")
    if env.get("DATA_DIR"):
        data_dir = Path(env["DATA_DIR"])

    return Settings(
        model_api_key=env.get("MODEL_API_KEY", ""),
        meta_api_base=env.get("META_API_BASE", "https://api.meta.ai/v1"),
        spark_model=env.get("SPARK_MODEL", "muse-spark-1.3"),
        wonder_model=env.get("WONDER_MODEL", "muse-wonder-1.0"),
        sam_model=env.get("SAM_MODEL", "sam-3.1"),
        asr_model=env.get("ASR_MODEL", "muse-voice-transcribe-1.0"),
        max_video_seconds=int(env.get("MAX_VIDEO_SECONDS", "600")),
        enable_inspector=enable_inspector,
        daily_job_limit=int(env.get("DAILY_JOB_LIMIT", "20")),
        pipeline_workers=int(env.get("PIPELINE_WORKERS", "4")),
        budget_usd=float(env.get("BUDGET_USD", "120.0")),
        job_budget_usd=float(env.get("JOB_BUDGET_USD", "2.5")),
        agent_budget_usd=float(env.get("AGENT_BUDGET_USD", "1.0")),
        live_budget_usd=float(env.get("LIVE_BUDGET_USD", "2.0")),
        live_max_calls=int(env.get("LIVE_MAX_CALLS", "300")),
        visitor_videos_per_day=int(env.get("VISITOR_VIDEOS_PER_DAY", "0")),
        visitor_coach_minutes_per_day=int(env.get("VISITOR_COACH_MINUTES_PER_DAY", "0")),
        visitor_questions_per_hour=int(env.get("VISITOR_QUESTIONS_PER_HOUR", "0")),
        visitor_actions_per_hour=int(env.get("VISITOR_ACTIONS_PER_HOUR", "0")),
        trust_proxy=_parse_bool(env.get("TRUST_PROXY", "false")),
        demo_job=env.get("DEMO_JOB", "").strip(),
        data_dir=data_dir,
        voice_model_dir=Path(env.get("VOICE_MODEL_DIR", "models/vits-mms-eng")),
    )
