"""Persistence of workbook versions and their RawWorkbook extraction."""

from __future__ import annotations

import gzip
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.parser.loader import load_raw_workbook
from app.parser.models import RawSheet, RawWorkbook, WorkbookSummary
from app.storage.models import RawSheetBlob, WorkbookVersion


class WorkbookNotFoundError(LookupError):
    pass


class SheetNotFoundError(LookupError):
    pass


def new_version_id() -> str:
    return uuid.uuid4().hex


def _pack(sheet: RawSheet) -> bytes:
    return gzip.compress(sheet.model_dump_json().encode("utf-8"), compresslevel=6)


def _unpack(payload: bytes) -> RawSheet:
    return RawSheet.model_validate_json(gzip.decompress(payload))


def ingest_workbook(
    session: Session, path: Path, *, filename: str, version_id: str | None = None
) -> WorkbookVersion:
    """Parse ``path`` and persist it as a new immutable workbook version.

    Sheets are written as they are extracted, so peak memory is one sheet, not the workbook.
    On failure the transaction is rolled back and nothing is left behind in the database.
    """
    version = WorkbookVersion(
        id=version_id or new_version_id(),
        filename=filename,
        uploaded_at=datetime.now(UTC),
        status="parsing",
        file_path=str(path),
        size_bytes=path.stat().st_size,
    )
    session.add(version)
    session.flush()

    def on_sheet(sheet: RawSheet) -> None:
        session.add(
            RawSheetBlob(
                version_id=version.id,
                sheet_name=sheet.name,
                sheet_index=sheet.index,
                cell_count=sheet.cell_count,
                formula_count=sheet.formula_count,
                payload=_pack(sheet),
            )
        )
        session.flush()

    started = time.perf_counter()
    try:
        raw = load_raw_workbook(path, filename=filename, on_sheet=on_sheet, keep_cells=False)
    except Exception:
        session.rollback()
        raise

    version.parse_seconds = round(time.perf_counter() - started, 3)
    version.summary_json = raw.summary().model_dump_json()
    version.meta_json = raw.model_dump_json()
    version.status = "uploaded"
    session.commit()
    session.refresh(version)
    return version


def get_version(session: Session, version_id: str) -> WorkbookVersion:
    version = session.get(WorkbookVersion, version_id)
    if version is None:
        raise WorkbookNotFoundError(version_id)
    return version


def list_versions(session: Session) -> list[WorkbookVersion]:
    stmt = select(WorkbookVersion).order_by(WorkbookVersion.uploaded_at.desc())
    return list(session.scalars(stmt))


def summary_of(version: WorkbookVersion) -> WorkbookSummary | None:
    if not version.summary_json:
        return None
    return WorkbookSummary.model_validate_json(version.summary_json)


def load_raw(session: Session, version_id: str, *, sheet: str | None = None) -> RawWorkbook:
    """Rebuild the RawWorkbook (all sheets, or one) from storage."""
    version = get_version(session, version_id)
    if not version.meta_json:
        raise WorkbookNotFoundError(f"{version_id} has no parsed content (status={version.status})")
    raw = RawWorkbook.model_validate_json(version.meta_json)

    stmt = (
        select(RawSheetBlob)
        .where(RawSheetBlob.version_id == version_id)
        .order_by(RawSheetBlob.sheet_index)
    )
    if sheet is not None:
        stmt = stmt.where(RawSheetBlob.sheet_name == sheet)
    blobs = list(session.scalars(stmt))
    if sheet is not None and not blobs:
        raise SheetNotFoundError(sheet)

    loaded = {blob.sheet_name: _unpack(blob.payload) for blob in blobs}
    raw.sheets = [loaded[s.name] for s in raw.sheets if s.name in loaded]
    return raw
