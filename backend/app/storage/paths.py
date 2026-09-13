"""Stored file paths are relative to the data directory, so the whole data folder can move
(a backup restore, a new machine) and every row still resolves. Older rows that hold an
absolute path are rebased by their ``workbooks/…`` or ``exports/…`` suffix when the absolute
path no longer exists."""

from __future__ import annotations

from pathlib import Path, PurePath

from app.config import get_settings

ROOTS = ("workbooks", "exports")


def to_stored(path: Path) -> str:
    """The string to persist: relative (posix) inside the data dir, absolute otherwise."""
    data_dir = get_settings().data_dir.resolve()
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(data_dir).as_posix()
    except ValueError:
        return str(resolved)


def resolve_stored(stored: str | None) -> Path | None:
    """The file a stored path points at today, or None when it cannot be found."""
    if not stored:
        return None
    data_dir = get_settings().data_dir
    raw = PurePath(stored)
    if raw.is_absolute():
        candidate = Path(stored)
        if candidate.exists():
            return candidate
        parts = raw.parts
        for i, part in enumerate(parts):
            if part in ROOTS and i < len(parts) - 1:
                rebased = data_dir.joinpath(*parts[i:])
                if rebased.exists():
                    return rebased
        return None
    candidate = data_dir / raw
    return candidate if candidate.exists() else None
