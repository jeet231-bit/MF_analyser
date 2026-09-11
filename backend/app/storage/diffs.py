"""Compute and persist DiffReports between two versions."""

from __future__ import annotations

import gzip

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.model.diff import DiffReport, diff_models
from app.parser.models import RawWorkbook
from app.storage import logic, validation, workbooks
from app.storage.models import DiffRow


def _raw_loader(session: Session, version_id: str):
    cache: dict[str, object] = {}

    def load(name: str):
        if name not in cache:
            try:
                cache[name] = workbooks.load_raw(session, version_id, sheet=name).sheets[0]
            except workbooks.SheetNotFoundError:
                cache[name] = None
        return cache[name]

    return load


def compute_diff(session: Session, base_id: str, target_id: str) -> DiffReport:
    base_model = logic.get_model(session, base_id)
    target_model = logic.get_model(session, target_id)
    base_meta = RawWorkbook.model_validate_json(
        workbooks.get_version(session, base_id).meta_json or "{}"
    )
    target_meta = RawWorkbook.model_validate_json(
        workbooks.get_version(session, target_id).meta_json or "{}"
    )

    def anomalies(version_id: str):
        try:
            return validation.latest_validation(session, version_id).anomalies
        except validation.ValidationNotFoundError:
            return None

    report = diff_models(
        base_model,
        target_model,
        base_names=base_meta.defined_names,
        target_names=target_meta.defined_names,
        base_raw=_raw_loader(session, base_id),
        target_raw=_raw_loader(session, target_id),
        base_anomalies=anomalies(base_id),
        target_anomalies=anomalies(target_id),
    )
    row = session.get(DiffRow, (base_id, target_id))
    payload = gzip.compress(report.model_dump_json().encode("utf-8"), compresslevel=6)
    if row is None:
        session.add(
            DiffRow(
                base_version_id=base_id,
                target_version_id=target_id,
                created_at=report.created_at,
                headline=report.headline,
                payload=payload,
            )
        )
    else:
        row.created_at, row.headline, row.payload = report.created_at, report.headline, payload
    session.commit()
    return report


def get_diff(
    session: Session, base_id: str, target_id: str, *, refresh: bool = False
) -> DiffReport:
    if not refresh:
        row = session.get(DiffRow, (base_id, target_id))
        if row is not None:
            return DiffReport.model_validate_json(gzip.decompress(row.payload))
    return compute_diff(session, base_id, target_id)


def latest_diff_for(session: Session, target_id: str) -> DiffRow | None:
    stmt = (
        select(DiffRow)
        .where(DiffRow.target_version_id == target_id)
        .order_by(DiffRow.created_at.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()
