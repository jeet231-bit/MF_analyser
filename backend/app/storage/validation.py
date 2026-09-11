"""Run validation for a version, persist the report, and enforce the activation gate."""

from __future__ import annotations

import gzip
import json
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.storage import runs, workbooks
from app.storage.models import ValidationRow, WorkbookVersion
from app.validation.anomalies import find_anomalies
from app.validation.reconcile import reconcile
from app.validation.schema import ValidationPolicy, ValidationReport


class ValidationNotFoundError(LookupError):
    pass


class ActivationRefusedError(Exception):
    def __init__(self, message: str, *, status: str | None) -> None:
        super().__init__(message)
        self.validation_status = status


def default_policy() -> ValidationPolicy:
    s = get_settings()
    return ValidationPolicy(
        max_mismatch_ratio=s.validation_max_mismatch_ratio,
        max_precision_ratio=s.validation_max_precision_ratio,
    )


def decide_status(
    report_totals, mismatches, anomalies, policy: ValidationPolicy
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    checked = report_totals.checked
    if checked == 0:
        return "failed", [
            "no formula cell could be checked (no cached values, or nothing in scope)"
        ]
    hard = sum(1 for m in mismatches if m.classification in ("semantics", "data"))
    precision = sum(1 for m in mismatches if m.classification == "precision")
    # Counts above the stored cap are unknown by class; treat them as hard.
    hard += max(0, report_totals.mismatched - len(mismatches))
    status = "passed"
    if hard / checked > policy.max_mismatch_ratio:
        status = "failed"
        reasons.append(f"{hard:,} of {checked:,} checked cells differ from Excel beyond precision")
    if precision / checked > policy.max_precision_ratio:
        status = "failed"
        reasons.append(
            f"{precision:,} precision mismatches exceed the allowed ratio {policy.max_precision_ratio}"
        )
    if status == "failed":
        return status, reasons
    if precision:
        reasons.append(f"{precision:,} cell(s) differ only in floating-point precision")
    if report_totals.skipped_unsupported:
        reasons.append(
            f"{report_totals.skipped_unsupported:,} cell(s) use functions the engine does not support and were skipped"
        )
    if report_totals.skipped_stale:
        reasons.append(
            f"{report_totals.skipped_stale:,} formula cell(s) have no cached value in the file and were skipped"
        )
    if anomalies:
        reasons.append(f"{len(anomalies)} structural anomaly warning(s)")
    return ("passed_with_warnings" if reasons else "passed"), reasons


def validate_version(
    session: Session, version_id: str, policy: ValidationPolicy | None = None
) -> ValidationReport:
    policy = policy or default_policy()
    started = time.perf_counter()
    engine, model, _meta, version = runs.load_engine(session, version_id)
    result = engine.run({}, mode="full", skip_unsupported=True)
    run = runs.save_run(session, version, result, parent_run_id=None)
    if not result.summary.skipped_template_ids:
        runs.state_cache.put((version_id, run.id), (result.grids, result.table))

    def load_raw(name: str):
        return workbooks.load_raw(session, version_id, sheet=name).sheets[0]

    raw_sheets = {s.name: load_raw(s.name) for s in model.sheets if s.in_scope and s.formula_cells}
    computed_cache: dict[str, dict] = {}

    def computed(sheet: str) -> dict:
        if sheet not in computed_cache:
            cols = result.formula_values(sheet)
            computed_cache[sheet] = {
                a: (v, t)
                for a, v, t in zip(cols["address"], cols["value"], cols["type"], strict=True)
            }
        return computed_cache[sheet]

    totals, coverage, mismatches, truncated, unsupported = reconcile(
        model, raw_sheets, computed, set(result.summary.skipped_template_ids), policy
    )
    anomalies = find_anomalies(model, lambda name: raw_sheets.get(name) or load_raw(name))
    status, reasons = decide_status(totals, mismatches, anomalies, policy)
    counts: dict[str, int] = {}
    for a in anomalies:
        counts[a.kind] = counts.get(a.kind, 0) + 1
    report = ValidationReport(
        id=uuid.uuid4().hex,
        version_id=version_id,
        run_id=run.id,
        created_at=datetime.now(UTC),
        status=status,  # type: ignore[arg-type]
        policy=policy,
        totals=totals,
        by_sheet=coverage,
        mismatches=mismatches,
        mismatches_truncated=truncated,
        unsupported=unsupported,
        anomalies=anomalies,
        anomaly_counts=counts,
        reasons=reasons,
        seconds=round(time.perf_counter() - started, 2),
    )
    session.add(
        ValidationRow(
            id=report.id,
            version_id=version_id,
            run_id=run.id,
            status=status,
            created_at=report.created_at,
            summary_json=json.dumps(
                {
                    "status": status,
                    "totals": totals.model_dump(),
                    "anomaly_counts": counts,
                    "reasons": reasons,
                }
            ),
            payload=gzip.compress(report.model_dump_json().encode("utf-8"), compresslevel=6),
        )
    )
    if version.status in ("uploaded", "interpreted", "validated") and status != "failed":
        version.status = "validated"
    session.commit()
    return report


def latest_validation(session: Session, version_id: str) -> ValidationReport:
    stmt = (
        select(ValidationRow)
        .where(ValidationRow.version_id == version_id)
        .order_by(ValidationRow.created_at.desc())
        .limit(1)
    )
    row = session.scalars(stmt).first()
    if row is None:
        raise ValidationNotFoundError(version_id)
    return ValidationReport.model_validate_json(gzip.decompress(row.payload))


def latest_status(session: Session, version_id: str) -> str | None:
    stmt = (
        select(ValidationRow.status)
        .where(ValidationRow.version_id == version_id)
        .order_by(ValidationRow.created_at.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def activate_version(
    session: Session, version_id: str, override_reason: str | None
) -> WorkbookVersion:
    """Activate a version: latest validation must be passed / passed_with_warnings, or an
    explicit override reason must be given for a failed one. Deactivates the previous active version."""
    version = workbooks.get_version(session, version_id)
    status = latest_status(session, version_id)
    if status is None:
        raise ActivationRefusedError("Validate this version before activating it.", status=None)
    override = False
    if status == "failed":
        if not override_reason or not override_reason.strip():
            raise ActivationRefusedError(
                "The latest validation failed; activation needs an explicit override reason.",
                status=status,
            )
        override = True
    for other in session.scalars(select(WorkbookVersion).where(WorkbookVersion.status == "active")):
        if other.id != version.id:
            other.status = "validated"
    version.status = "active"
    version.activated_at = datetime.now(UTC)
    version.activation_override = override
    version.activation_reason = (
        override_reason.strip() if override else f"validation {status.replace('_', ' ')}"
    )
    session.commit()
    session.refresh(version)
    return version
