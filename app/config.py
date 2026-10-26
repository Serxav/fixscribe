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
    budget_usd: float = 120.0  # [BUDGET_USD]
    job_budget_usd: float = 1.0  # [JOB_BUDGET_USD]
    data_dir: Path = Path("data")  # [DATA_DIR]


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
        budget_usd=float(env.get("BUDGET_USD", "120.0")),
        job_budget_usd=float(env.get("JOB_BUDGET_USD", "1.0")),
        data_dir=data_dir,
    )
