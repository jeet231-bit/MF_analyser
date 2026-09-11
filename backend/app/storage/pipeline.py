"""Post-upload pipeline: interpret -> validate -> diff against the active version -> pending review."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dashboard_config import load_dashboard_config
from app.storage import diffs, logic, validation
from app.storage.models import WorkbookVersion

log = logging.getLogger(__name__)


def active_version(session: Session, exclude_id: str | None = None) -> WorkbookVersion | None:
    stmt = select(WorkbookVersion).where(WorkbookVersion.status == "active")
    for row in session.scalars(stmt):
        if row.id != exclude_id:
            return row
    return None


def process_upload(session: Session, version: WorkbookVersion) -> list[str]:
    """Run the standard pipeline on a freshly ingested version. Never raises; returns notes."""
    notes: list[str] = []
    try:
        logic.interpret_version(session, version.id, scope=None, config=load_dashboard_config())
    except Exception as exc:  # noqa: BLE001 - the upload itself succeeded; report, do not fail
        log.warning("interpretation failed for %s: %s", version.id, exc)
        notes.append(f"interpretation failed: {exc}")
        return notes
    try:
        report = validation.validate_version(session, version.id)
        note = f"validation {report.status.replace('_', ' ')}"
        if report.status == "failed" and report.reasons:
            note += f": {report.reasons[0]}"
        notes.append(note)
    except Exception as exc:  # noqa: BLE001
        log.warning("validation failed for %s: %s", version.id, exc)
        notes.append(f"validation failed: {exc}")
    active = active_version(session, exclude_id=version.id)
    if active is not None:
        try:
            report = diffs.compute_diff(session, active.id, version.id)
            notes.append(f"diff vs active: {report.headline}")
        except Exception as exc:  # noqa: BLE001
            log.warning("diff failed for %s: %s", version.id, exc)
            notes.append(f"diff failed: {exc}")
    version.status = "pending_review"
    session.commit()
    return notes
