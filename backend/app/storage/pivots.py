"""The pivot definitions of a version. New uploads carry them in ``meta_json``; versions
ingested before pivots were parsed get them from the stored file on first request."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.parser.loader import PIVOT_WARNING
from app.parser.models import PivotSpec, RawWorkbook
from app.parser.pivots import parse_pivots
from app.storage.models import WorkbookVersion
from app.storage.paths import resolve_stored

log = logging.getLogger(__name__)
_cache: dict[str, list[PivotSpec]] = {}


def pivot_id(spec: PivotSpec) -> str:
    """Stable id: pivot names repeat across sheets, sheet + name does not."""
    return f"{spec.sheet}::{spec.name}"


def specs_for(session: Session, version: WorkbookVersion) -> list[PivotSpec]:
    hit = _cache.get(version.id)
    if hit is not None:
        return hit
    specs: list[PivotSpec] = []
    if version.meta_json:
        raw = RawWorkbook.model_validate_json(version.meta_json)
        specs = raw.pivots
        # Re-parse when nothing is stored yet, or when an older parse predates a field.
        stale = bool(specs) and all(sp.refreshed is None for sp in specs)
        if (not specs or stale) and PIVOT_WARNING in raw.warnings:
            path = resolve_stored(version.file_path)
            if path is not None:
                try:
                    specs = parse_pivots(path)
                except Exception as exc:  # noqa: BLE001 - a bad part must not break the API
                    log.warning("could not parse pivots of %s: %s", version.id[:8], exc)
                    specs = []
                if specs and any(sp.refreshed for sp in specs):
                    raw.pivots = specs
                    version.meta_json = raw.model_dump_json()
                    session.commit()
    _cache[version.id] = specs
    return specs


def find(session: Session, version: WorkbookVersion, pid: str) -> PivotSpec | None:
    return next((s for s in specs_for(session, version) if pivot_id(s) == pid), None)


def clear() -> None:
    _cache.clear()
