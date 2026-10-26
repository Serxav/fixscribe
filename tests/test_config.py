"""Settings tests: env parsing, defaults and secret redaction."""

import pytest

import app.config
from app.config import get_settings

ENV_KEYS = [
    "MODEL_API_KEY",
    "META_API_BASE",
    "SPARK_MODEL",
    "WONDER_MODEL",
    "SAM_MODEL",
    "ASR_MODEL",
    "MAX_VIDEO_SECONDS",
    "ENABLE_INSPECTOR",
    "DAILY_JOB_LIMIT",
    "BUDGET_USD",
    "DATA_DIR",
]


@pytest.fixture(autouse=True)
def isolated_dotenv(monkeypatch):
    """Block the real `.env` file: load_dotenv resolves it from our file
    location, not the cwd, so chdir alone cannot isolate these tests."""
    calls: list[bool] = []
    monkeypatch.setattr(app.config, "load_dotenv", lambda override=False: calls.append(override))
    return calls


@pytest.fixture
def clean_env(monkeypatch, isolated_dotenv):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return isolated_dotenv


def test_env_values_are_read(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODEL_API_KEY", "secret-key")
    monkeypatch.setenv("META_API_BASE", "https://example.test/v1")
    monkeypatch.setenv("SPARK_MODEL", "muse-spark-1.3")
    monkeypatch.setenv("WONDER_MODEL", "muse-wonder-1.0")
    monkeypatch.setenv("SAM_MODEL", "sam-3.1")
    monkeypatch.setenv("ASR_MODEL", "muse-voice-transcribe-1.0")
    monkeypatch.setenv("MAX_VIDEO_SECONDS", "300")
    monkeypatch.setenv("ENABLE_INSPECTOR", "yes")
    monkeypatch.setenv("DAILY_JOB_LIMIT", "5")
    monkeypatch.setenv("BUDGET_USD", "10.5")
    monkeypatch.setenv("DATA_DIR", "custom-data")

    settings = get_settings()

    assert settings.model_api_key == "secret-key"
    assert settings.meta_api_base == "https://example.test/v1"
    assert settings.max_video_seconds == 300
    assert settings.enable_inspector is True
    assert settings.daily_job_limit == 5
    assert settings.budget_usd == pytest.approx(10.5)
    assert str(settings.data_dir) == "custom-data"


@pytest.mark.parametrize("value", ["true", "1", "yes", "True", "YES"])
def test_enable_inspector_truthy(monkeypatch, tmp_path, value):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODEL_API_KEY", "k")
    monkeypatch.setenv("ENABLE_INSPECTOR", value)
    assert get_settings().enable_inspector is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off", ""])
def test_enable_inspector_falsy(monkeypatch, tmp_path, value):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODEL_API_KEY", "k")
    monkeypatch.setenv("ENABLE_INSPECTOR", value)
    assert get_settings().enable_inspector is False


def test_defaults_without_env(clean_env):
    settings = get_settings()
    assert settings.model_api_key == ""
    assert settings.meta_api_base == "https://api.meta.ai/v1"
    assert settings.spark_model == "muse-spark-1.3"
    assert settings.wonder_model == "muse-wonder-1.0"
    assert settings.sam_model == "sam-3.1"
    assert settings.asr_model == "muse-voice-transcribe-1.0"
    assert settings.max_video_seconds == 600
    assert settings.enable_inspector is True
    assert settings.daily_job_limit == 20
    assert settings.budget_usd == pytest.approx(120.0)
    assert str(settings.data_dir) == "data"


def test_api_key_not_in_repr(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODEL_API_KEY", "secret-key")
    assert "secret-key" not in repr(get_settings())


def test_loads_dotenv_without_override(clean_env):
    get_settings()
    assert clean_env == [False]
