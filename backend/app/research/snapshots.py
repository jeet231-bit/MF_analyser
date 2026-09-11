"""Per-version snapshots: entity key -> (rank, quartile, score, label, category) for every
version that has been activated. Written at activation (and on first demand for versions
activated before snapshots existed), so held-Q1 consistency, fund history and movement read a
few kilobytes per version instead of rebuilding each version's research table. That cost was
linear in the number of monthly uploads; snapshots make it flat.

A "genuine" upload is one with a new as-of date (or, when the map declares no as-of cell, a
different rank vector). Two uploads of the same month collapse to the latest activated one, so
"held Q1 across N versions" counts months, never re-uploads of the same master."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.research.table import NotConfigured, ResearchTable, get_table
from app.storage import runs, workbooks
from app.storage.models import ResearchSnapshot, WorkbookVersion


@dataclass
class SnapshotRow:
    rank: float | None
    quartile: float | None
    score: float | None
    label: str
    category: str | None


@dataclass
class Snapshot:
    version_id: str
    filename: str
    uploaded_at: datetime
    activated_at: datetime | None
    run_id: str
    as_of: Any
    fingerprint: str
    rows: dict[str, SnapshotRow]
    _rated_by_category: dict[str, int] | None = field(default=None, repr=False)

    @property
    def date(self) -> datetime:
        """The month the snapshot describes: the as-of date when the map has one, else upload.
        Always naive, so snapshots with and without an as-of date compare."""
        d = as_of_datetime(self.as_of)
        return _naive(d if d is not None else self.uploaded_at)

    @property
    def order_key(self) -> tuple[datetime, datetime]:
        return (self.date, _naive(self.activated_at or self.uploaded_at))


def _naive(d: datetime) -> datetime:
    return d.astimezone(UTC).replace(tzinfo=None) if d.tzinfo else d

    def rated_in_category(self, category: str | None) -> int:
        if self._rated_by_category is None:
            counts: dict[str, int] = {}
            for r in self.rows.values():
                if r.quartile is not None and r.category:
                    counts[r.category] = counts.get(r.category, 0) + 1
            self._rated_by_category = counts
        return self._rated_by_category.get(category or "", 0)


def as_of_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        from openpyxl.utils.datetime import from_excel

        try:
            return from_excel(float(value))
        except (ValueError, OverflowError, TypeError):
            return None
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d %B %Y", "%b %Y"):
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                continue
    return None


def _fingerprint(table: ResearchTable, rank_key: str | None, q_key: str | None) -> str:
    d = as_of_datetime(table.as_of)
    if d is not None:
        return "asof:" + d.date().isoformat()
    h = hashlib.sha1()
    for e in sorted(table.entities, key=lambda x: x.key):
        r = e.measures.get(rank_key) if rank_key else None
        q = e.measures.get(q_key) if q_key else None
        h.update(f"{e.key}\t{r}\t{q}\n".encode())
    return "ranks:" + h.hexdigest()[:24]


def build_payload(table: ResearchTable) -> tuple[dict[str, list[Any]], str]:
    rank_key, q_key, s_key = (table.primary_key(r) for r in ("rank", "quartile", "score"))
    rows: dict[str, list[Any]] = {}
    for e in table.entities:
        rows[e.key] = [
            e.measures.get(rank_key) if rank_key else None,
            e.measures.get(q_key) if q_key else None,
            e.measures.get(s_key) if s_key else None,
            e.label,
            e.category,
        ]
    return rows, _fingerprint(table, rank_key, q_key)


_unpacked: dict[tuple[str, str], Snapshot] = {}  # (version, run) -> snapshot, in-process
_UNPACKED_CAP = 64


def _unpack(row: ResearchSnapshot, version: WorkbookVersion) -> Snapshot:
    key = (version.id, row.run_id)
    hit = _unpacked.get(key)
    if hit is not None:
        hit.activated_at = version.activated_at  # activation state may have moved on
        return hit
    data = json.loads(gzip.decompress(row.payload).decode("utf-8"))
    snap = Snapshot(
        version_id=version.id,
        filename=version.filename,
        uploaded_at=version.uploaded_at,
        activated_at=version.activated_at,
        run_id=row.run_id,
        as_of=data.get("as_of"),
        fingerprint=row.fingerprint,
        rows={k: SnapshotRow(*v) for k, v in data["rows"].items()},
    )
    if len(_unpacked) >= _UNPACKED_CAP:
        _unpacked.pop(next(iter(_unpacked)))
    _unpacked[key] = snap
    return snap


def ensure_snapshot(session: Session, version: WorkbookVersion) -> Snapshot | None:
    """The version's snapshot, taken now from its baseline run when missing or stale. None when
    the version has no baseline run or the research map does not resolve on it."""
    run = runs.baseline_run(session, version.id)
    if run is None:
        return None
    existing = session.get(ResearchSnapshot, version.id)
    if existing is not None and existing.run_id == run.id:
        return _unpack(existing, version)
    try:
        table = get_table(session, version, run)
    except NotConfigured:
        return None
    rows, fingerprint = build_payload(table)
    as_of = table.as_of
    if isinstance(as_of, datetime):
        as_of = as_of.isoformat()
    payload = gzip.compress(
        json.dumps({"as_of": as_of, "rows": rows}, separators=(",", ":")).encode("utf-8")
    )
    if existing is None:
        existing = ResearchSnapshot(version_id=version.id)
        session.add(existing)
    existing.run_id = run.id
    existing.created_at = datetime.now(UTC)
    existing.as_of = str(as_of)[:64] if as_of is not None else None
    existing.fingerprint = fingerprint
    existing.entity_count = len(rows)
    existing.payload = payload
    session.commit()
    return _unpack(existing, version)


def activated_snapshots(session: Session) -> list[Snapshot]:
    """One snapshot per version that has ever been activated, oldest activation first."""
    versions = [v for v in workbooks.list_versions(session) if v.activated_at is not None]
    versions.sort(key=lambda v: _naive(v.activated_at))  # type: ignore[arg-type]
    stored = {
        r.version_id: r
        for r in session.scalars(
            select(ResearchSnapshot).where(
                ResearchSnapshot.version_id.in_([v.id for v in versions])
            )
        )
    }
    out: list[Snapshot] = []
    for v in versions:
        row = stored.get(v.id)
        run = runs.baseline_run(session, v.id)
        if run is None:
            continue
        snap = _unpack(row, v) if row is not None and row.run_id == run.id else None
        if snap is None:
            snap = ensure_snapshot(session, v)
        if snap is not None:
            out.append(snap)
    return out


def genuine(snapshots: list[Snapshot]) -> list[Snapshot]:
    """Distinct months only: the latest activated snapshot per fingerprint, in date order."""
    latest: dict[str, Snapshot] = {}
    for s in snapshots:  # oldest activation first, so later ones win
        latest[s.fingerprint] = s
    return sorted(latest.values(), key=lambda s: s.order_key)


def snapshot_for(session: Session, version: WorkbookVersion) -> Snapshot | None:
    return ensure_snapshot(session, version)


def date_label(snapshot: Snapshot | None, relative_to: Snapshot | None = None) -> str | None:
    """'31 Aug' when the year matches the current snapshot's, else '31 Aug 2025'."""
    if snapshot is None:
        return None
    d = snapshot.date
    if relative_to is not None and relative_to.date.year == d.year:
        return d.strftime("%d %b").lstrip("0")
    return d.strftime("%d %b %Y").lstrip("0")
