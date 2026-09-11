import logging
import re
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.parser.loader import SUPPORTED_SUFFIXES, UnsupportedFileError
from app.parser.models import RawWorkbook, WorkbookSummary
from app.storage import diffs as diffs_store
from app.storage import validation as validation_store
from app.storage import workbooks as store
from app.storage.db import get_session
from app.storage.models import WorkbookVersion
from app.storage.pipeline import process_upload

log = logging.getLogger(__name__)
router = APIRouter(prefix="/workbooks")

SessionDep = Annotated[Session, Depends(get_session)]
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


class WorkbookVersionOut(BaseModel):
    id: str
    filename: str
    uploaded_at: datetime
    status: str
    size_bytes: int
    parse_seconds: float | None = None
    summary: WorkbookSummary | None = None
    activated_at: datetime | None = None
    activation_reason: str | None = None
    activation_override: bool = False
    validation_status: str | None = None
    diff_base_id: str | None = None
    diff_headline: str | None = None
    pipeline_notes: list[str] = []

    @classmethod
    def from_row(cls, row: WorkbookVersion, session: Session | None = None) -> "WorkbookVersionOut":
        uploaded_at = row.uploaded_at
        if uploaded_at.tzinfo is None:  # SQLite stores naive timestamps; ours are always UTC
            uploaded_at = uploaded_at.replace(tzinfo=UTC)
        activated_at = row.activated_at
        if activated_at is not None and activated_at.tzinfo is None:
            activated_at = activated_at.replace(tzinfo=UTC)
        diff_row = diffs_store.latest_diff_for(session, row.id) if session else None
        return cls(
            id=row.id,
            filename=row.filename,
            uploaded_at=uploaded_at,
            status=row.status,
            size_bytes=row.size_bytes,
            parse_seconds=row.parse_seconds,
            summary=store.summary_of(row),
            activated_at=activated_at,
            activation_reason=row.activation_reason,
            activation_override=bool(row.activation_override),
            validation_status=validation_store.latest_status(session, row.id) if session else None,
            diff_base_id=diff_row.base_version_id if diff_row else None,
            diff_headline=diff_row.headline if diff_row else None,
        )


def _safe_filename(name: str | None) -> str:
    base = Path(name or "workbook.xlsx").name
    base = _SAFE_NAME.sub("_", base).strip() or "workbook.xlsx"
    return base


def _save_upload(upload: UploadFile, target_dir: Path, limit_bytes: int) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _safe_filename(upload.filename)
    written = 0
    with target.open("wb") as out:
        while chunk := upload.file.read(1024 * 1024):
            written += len(chunk)
            if written > limit_bytes:
                out.close()
                shutil.rmtree(target_dir, ignore_errors=True)
                raise HTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    f"File exceeds the upload limit of {limit_bytes // (1024 * 1024)} MB.",
                )
            out.write(chunk)
    return target


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WorkbookVersionOut)
def upload_workbook(session: SessionDep, file: Annotated[UploadFile, File()]) -> WorkbookVersionOut:
    """Upload an .xlsx/.xlsm master workbook; parses it into a new immutable version."""
    settings = get_settings()
    filename = _safe_filename(file.filename)
    suffix = Path(filename).suffix.lower()
    if suffix == ".xls":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Legacy binary .xls files are not supported. Open the file in Excel, save as .xlsx and upload again.",
        )
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file type '{suffix or 'none'}'. Upload an .xlsx or .xlsm workbook.",
        )

    version_id = store.new_version_id()
    version_dir = settings.data_dir / "workbooks" / version_id
    path = _save_upload(file, version_dir, settings.max_upload_mb * 1024 * 1024)

    try:
        version = store.ingest_workbook(session, path, filename=filename, version_id=version_id)
    except UnsupportedFileError as exc:
        shutil.rmtree(version_dir, ignore_errors=True)
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as exc:
        shutil.rmtree(version_dir, ignore_errors=True)
        log.warning("rejected upload %s: %s", filename, exc)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The file could not be read as an Excel workbook. It may be corrupt or not an Office Open XML file.",
        ) from exc
    notes = process_upload(session, version)
    out = WorkbookVersionOut.from_row(version, session)
    out.pipeline_notes = notes
    return out


@router.get("", response_model=list[WorkbookVersionOut])
def list_workbooks(session: SessionDep) -> list[WorkbookVersionOut]:
    return [WorkbookVersionOut.from_row(v, session) for v in store.list_versions(session)]


@router.get("/{version_id}", response_model=WorkbookVersionOut)
def get_workbook(version_id: str, session: SessionDep) -> WorkbookVersionOut:
    try:
        return WorkbookVersionOut.from_row(store.get_version(session, version_id), session)
    except store.WorkbookNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workbook version not found.") from exc


@router.get("/{version_id}/raw", response_model=RawWorkbook)
def get_raw_workbook(
    version_id: str,
    session: SessionDep,
    sheet: Annotated[str | None, Query(description="Restrict to one sheet by name")] = None,
) -> RawWorkbook:
    """The RawWorkbook extraction: every non-empty cell with formula, cached value and type."""
    try:
        return store.load_raw(session, version_id, sheet=sheet)
    except store.SheetNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Sheet '{sheet}' not found in this version."
        ) from exc
    except store.WorkbookNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workbook version not found.") from exc
