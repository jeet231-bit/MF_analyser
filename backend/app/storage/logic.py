"""Persistence of WorkbookLogicModels and sheet-role overrides."""

from __future__ import annotations

import gzip
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dashboard_config import DashboardConfig
from app.model.interpreter import InterpretOptions, interpret
from app.model.schema import WorkbookLogicModel
from app.parser.models import RawWorkbook
from app.storage import workbooks
from app.storage.models import LogicModelRow, SheetRoleOverride, WorkbookVersion


class ModelNotFoundError(LookupError):
    pass


def _user_overrides(session: Session, version_id: str) -> dict[str, tuple[str, str | None]]:
    stmt = select(SheetRoleOverride).where(SheetRoleOverride.version_id == version_id)
    return {row.sheet_name: (row.role, row.reason) for row in session.scalars(stmt)}


def interpret_version(
    session: Session,
    version_id: str,
    *,
    scope: list[str] | None,
    config: DashboardConfig,
) -> WorkbookLogicModel:
    version = workbooks.get_version(session, version_id)
    if not version.meta_json:
        raise workbooks.WorkbookNotFoundError(f"{version_id} has no parsed content")
    meta = RawWorkbook.model_validate_json(version.meta_json)

    def load_sheet(name: str):
        return workbooks.load_raw(session, version_id, sheet=name).sheets[0]

    # Config scope names belong to one particular master workbook; names that do not exist in
    # this workbook are ignored, and an empty match means "all sheets". Explicit API scopes stay strict.
    config_scope = [s for s in config.sheet_scope if s in meta.sheet_names] or None
    options = InterpretOptions(
        scope=scope if scope is not None else config_scope,
        config_role_overrides=dict(config.sheet_role_overrides),
        user_role_overrides=_user_overrides(session, version_id),
        output_sheets=list(config.output_sheets),
    )
    model = interpret(meta, load_sheet, version_id=version_id, options=options)
    save_model(session, version, model)
    return model


def save_model(session: Session, version: WorkbookVersion, model: WorkbookLogicModel) -> None:
    for old in list(version.logic_models):
        session.delete(old)
    session.flush()
    session.add(
        LogicModelRow(
            id=uuid.uuid4().hex,
            version_id=version.id,
            created_at=datetime.now(UTC),
            scope_json=json.dumps(model.scope),
            summary_json=model.summary.model_dump_json(),
            seconds=model.summary.seconds,
            peak_mb=model.summary.peak_mb,
            payload=gzip.compress(model.model_dump_json().encode("utf-8"), compresslevel=6),
        )
    )
    if version.status in ("uploaded", "interpreted"):
        version.status = "interpreted"
    session.commit()


def get_model(session: Session, version_id: str) -> WorkbookLogicModel:
    stmt = (
        select(LogicModelRow)
        .where(LogicModelRow.version_id == version_id)
        .order_by(LogicModelRow.created_at.desc())
        .limit(1)
    )
    row = session.scalars(stmt).first()
    if row is None:
        raise ModelNotFoundError(version_id)
    return WorkbookLogicModel.model_validate_json(gzip.decompress(row.payload))


def set_sheet_role(
    session: Session, version_id: str, sheet: str, role: str, reason: str | None
) -> WorkbookLogicModel:
    version = workbooks.get_version(session, version_id)
    model = get_model(session, version_id)
    target = model.sheet(sheet)
    if target is None:
        raise KeyError(sheet)
    stmt = select(SheetRoleOverride).where(
        SheetRoleOverride.version_id == version_id, SheetRoleOverride.sheet_name == sheet
    )
    row = session.scalars(stmt).first()
    if row is None:
        row = SheetRoleOverride(
            version_id=version_id, sheet_name=sheet, created_at=datetime.now(UTC)
        )
        session.add(row)
    row.role, row.reason, row.created_at = role, reason, datetime.now(UTC)

    target.role, target.role_source, target.role_reason = (
        role,
        "override",
        reason or "user override",
    )  # type: ignore[assignment]
    _reclassify(model)
    save_model(session, version, model)
    return model


def _reclassify(model: WorkbookLogicModel) -> None:
    readers = {b.id: 0 for b in model.formula_blocks}
    for e in model.edges:
        if e.source in readers and e.source != e.target:
            readers[e.source] += 1
    for s in model.sheets:
        s.output_cells = 0
    for b in model.formula_blocks:
        sheet = model.sheet(b.sheet)
        is_output = readers[b.id] == 0 or (sheet is not None and sheet.role == "output")
        b.classification = "output" if is_output else "calculation"
        if is_output and sheet is not None:
            sheet.output_cells += b.cell_count
    model.summary.output_cells = sum(s.output_cells for s in model.sheets)
