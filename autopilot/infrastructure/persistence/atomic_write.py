"""Atomic, crash-safe JSON file writes.

Shared by Ledger and RunRecordStore so that a save operation never leaves
the destination file in a partially-written state.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: str | Path, data: Any, *, indent: int = 2) -> None:
    """Write `data` as JSON to `path` atomically.

    Writes the serialized content to a temporary file in the same directory
    as `path`, flushes and closes it, then uses os.replace() to move it into
    place. If serialization or the write fails, the temporary file is removed
    and any pre-existing file at `path` is left untouched. If os.replace()
    itself fails, both the temporary file and any pre-existing file at `path`
    are left untouched.

    Args:
        path: Destination file path.
        data: JSON-serializable data to write.
        indent: Indentation level passed to json.dump.

    Raises:
        TypeError: If `data` is not JSON-serializable.
        OSError: If a filesystem error occurs while writing or replacing.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        _remove_if_exists(tmp_path)
        raise

    os.replace(tmp_path, destination)


def _remove_if_exists(path: Path) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
