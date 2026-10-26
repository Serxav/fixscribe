"""Read and write job artifacts: one typed model per file, one way to do it.

Writes are atomic (temp file, fsync, rename), so a reader never sees half a file. Reads raise
ArtifactError with the file name and the first bad field, so a stage fails with a clear message.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError


class ArtifactError(Exception):
    pass


def write_json_atomic(path: Path, data: Any) -> None:
    """Write JSON to a temp file in the same folder, then rename it over the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())
    os.replace(tmp.name, path)


def path_of(job_dir: Path, model: type[BaseModel]) -> Path:
    return job_dir / model.FILENAME  # type: ignore[attr-defined]


def exists(job_dir: Path, model: type[BaseModel]) -> bool:
    return path_of(job_dir, model).is_file()


def save(job_dir: Path, artifact: BaseModel) -> Path:
    path = path_of(job_dir, type(artifact))
    write_json_atomic(path, artifact.model_dump(mode="json"))
    return path


def load[M: BaseModel](job_dir: Path, model: type[M]) -> M:
    path = path_of(job_dir, model)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ArtifactError(f"missing {path.name}") from None
    except OSError as exc:
        raise ArtifactError(f"cannot read {path.name}: {exc.strerror}") from None
    try:
        return model.model_validate_json(text)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "file"
        raise ArtifactError(f"broken {path.name}: {where}: {first['msg']}") from None


def load_optional[M: BaseModel](job_dir: Path, model: type[M]) -> M | None:
    """None when the file does not exist (an optional stage did not run or failed)."""
    return load(job_dir, model) if exists(job_dir, model) else None
