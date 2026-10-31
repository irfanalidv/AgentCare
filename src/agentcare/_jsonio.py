"""Safe JSON file helpers for the local (no-database) storage backends.

Two problems these solve:

* **Data loss on corruption.** The JSON stores used to treat an unreadable file as
  empty and then overwrite it on the next write, silently deleting every stored
  customer / event. :func:`read_json` now moves a corrupt file aside
  (``<name>.corrupt-<timestamp>``) and logs a warning before returning the default.
* **Torn writes.** :func:`write_json_atomic` writes to a temporary file in the same
  folder and renames it into place, so a crash mid-write never leaves half a file.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Seconds to wait for a Postgres connection before giving up.
DB_CONNECT_TIMEOUT_SEC = 5


def read_json(path: Path, default: T, *, expected: type | tuple[type, ...]) -> T | Any:
    """Return the parsed JSON in ``path``, or ``default`` if it is missing or unusable.

    A file that exists but cannot be parsed, or whose top-level value is not of the
    ``expected`` type, is renamed to ``<name>.corrupt-<UTC timestamp>`` so the next
    write cannot destroy it, and a warning is logged.
    """
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _quarantine(path, f"unreadable JSON ({exc})")
        return default
    if not isinstance(data, expected):
        _quarantine(path, f"expected {expected}, found {type(data).__name__}")
        return default
    return data


def write_json_atomic(path: Path, data: Any, *, indent: int = 2) -> None:
    """Serialise ``data`` to ``path`` atomically (temp file + ``os.replace``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=indent, default=str)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _quarantine(path: Path, why: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        path.replace(target)
        logger.warning("%s: %s; moved aside to %s", path, why, target.name)
    except OSError as exc:  # pragma: no cover - e.g. read-only filesystem
        logger.warning("%s: %s; could not move it aside (%s)", path, why, exc)
