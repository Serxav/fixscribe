"""The one switch between the real Meta API and a fake (app.meta_client.make_client)."""

import ast
from pathlib import Path

from app import meta_client
from app.config import Settings

APP = Path(__file__).resolve().parents[1] / "app"


def test_no_app_module_builds_meta_client_directly():
    """Only meta_client.py may call MetaClient(...): everything else uses make_client()."""
    offenders = []
    for path in APP.rglob("*.py"):
        if path.name == "meta_client.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                if name == "MetaClient":
                    offenders.append(f"{path.relative_to(APP.parent)}:{node.lineno}")
    assert offenders == [], f"use make_client() instead of MetaClient(): {offenders}"


def test_make_client_uses_the_factory(tmp_path):
    seen = []

    class Fake:
        def __init__(self, settings, job_dir=None):
            seen.append(job_dir)

    meta_client.set_client_factory(Fake)
    try:
        assert isinstance(meta_client.make_client(Settings(), job_dir=tmp_path), Fake)
    finally:
        meta_client.set_client_factory(None)
    assert seen == [tmp_path]
    assert isinstance(meta_client.make_client(Settings(model_api_key="k")), meta_client.MetaClient)
