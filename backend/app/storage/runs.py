"""Persistence of engine runs and composition of their values on read."""

from __future__ import annotations

import gzip
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.runner import Engine, RunResult, RunSummary
from app.model.formula.refs import Rect, parse_a1_cell
from app.model.schema import WorkbookLogicModel
from app.parser.models import RawWorkbook
from app.storage import logic, workbooks
from app.storage.models import Run, RunSheetValues, WorkbookVersion


class RunNotFoundError(LookupError):
    pass


def _pack(columns: dict[str, list]) -> bytes:
    return gzip.compress(
        json.dumps(columns, separators=(",", ":")).encode("utf-8"), compresslevel=6
    )


def _unpack(payload: bytes) -> dict[str, list]:
    return json.loads(gzip.decompress(payload))


def load_engine(
    session: Session, version_id: str
) -> tuple[Engine, WorkbookLogicModel, RawWorkbook, WorkbookVersion]:
    version = workbooks.get_version(session, version_id)
    model = logic.get_model(session, version_id)
    meta = RawWorkbook.model_validate_json(version.meta_json or "{}")

    def load_sheet(name: str):
        return workbooks.load_raw(session, version_id, sheet=name).sheets[0]

    return Engine(model, meta, load_sheet), model, meta, version


def baseline_run(session: Session, version_id: str) -> Run | None:
    stmt = (
        select(Run)
        .where(
            Run.version_id == version_id,
            Run.kind == "full",
            Run.overrides_json == "{}",
            Run.status == "ok",
        )
        .order_by(Run.created_at.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def _seed_from(session: Session, run: Run) -> dict[str, dict[str, list]]:
    return {blob.sheet_name: _unpack(blob.payload) for blob in run.sheets}


class _StateCache:
    """In-process cache of a baseline run's final grids, so incremental runs skip reloading."""

    def __init__(self, capacity: int = 2) -> None:
        self.capacity = capacity
        self._items: dict[tuple[str, str], tuple[dict, Any]] = {}

    def get(self, key: tuple[str, str]):
        return self._items.get(key)

    def put(self, key: tuple[str, str], value) -> None:
        self._items[key] = value
        while len(self._items) > self.capacity:
            self._items.pop(next(iter(self._items)))

    def clear(self) -> None:
        self._items.clear()


state_cache = _StateCache()


def create_run(
    session: Session, version_id: str, overrides: dict[str, Any] | None, mode: str = "auto"
) -> Run:
    """Execute and persist a run. The first override-free full run becomes the baseline."""
    engine, model, _meta, version = load_engine(session, version_id)
    overrides = overrides or {}
    parent = baseline_run(session, version_id) if overrides and mode != "full" else None
    if parent is not None:
        cached = state_cache.get((version_id, parent.id))
        if cached is not None:
            result = engine.run(overrides, mode=mode, state=cached)
        else:
            result = engine.run(overrides, mode=mode, seed=_seed_from(session, parent))
    else:
        result = engine.run(overrides, mode=mode)
    run = save_run(
        session, version, result, parent_run_id=parent.id if parent is not None else None
    )
    if result.kind == "full" and not overrides:
        state_cache.put((version_id, run.id), (result.grids, result.table))
    return run


def save_run(
    session: Session, version: WorkbookVersion, result: RunResult, *, parent_run_id: str | None
) -> Run:
    run = Run(
        id=uuid.uuid4().hex,
        version_id=version.id,
        kind=result.kind,
        parent_run_id=parent_run_id,
        overrides_json=json.dumps(result.overrides, sort_keys=True),
        status="ok",
        summary_json=result.summary.model_dump_json(),
        created_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    only_evaluated = result.kind == "incremental"
    for sheet in [s.name for s in result.model.sheets if s.in_scope]:
        cols = result.formula_values(sheet, only_evaluated=only_evaluated)
        if not cols["address"]:
            continue
        session.add(
            RunSheetValues(
                run_id=run.id,
                sheet_name=sheet,
                cell_count=len(cols["address"]),
                payload=_pack(cols),
            )
        )
    session.commit()
    session.refresh(run)
    return run


def get_run(session: Session, run_id: str) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    return run


def list_runs(session: Session, version_id: str) -> list[Run]:
    stmt = select(Run).where(Run.version_id == version_id).order_by(Run.created_at.desc())
    return list(session.scalars(stmt))


def summary_of(run: Run) -> RunSummary:
    return RunSummary.model_validate_json(run.summary_json)


def overrides_of(run: Run) -> dict[str, Any]:
    return json.loads(run.overrides_json)


def formula_values(session: Session, run: Run, sheet: str) -> dict[str, tuple[Any, str]]:
    """address -> (value, type) for a sheet, composing parent runs beneath incremental runs."""
    chain: list[Run] = []
    current: Run | None = run
    while current is not None:
        chain.append(current)
        current = session.get(Run, current.parent_run_id) if current.parent_run_id else None
    out: dict[str, tuple[Any, str]] = {}
    for r in reversed(chain):
        for blob in r.sheets:
            if blob.sheet_name != sheet:
                continue
            cols = _unpack(blob.payload)
            for addr, value, vtype in zip(
                cols["address"], cols["value"], cols["type"], strict=True
            ):
                out[addr] = (value, vtype)
    return out


def sheet_values(
    session: Session, run: Run, sheet: str, rect: Rect | None = None
) -> list[dict[str, Any]]:
    """All non-empty cells of a sheet for a run: inputs (raw + overrides) and computed formulas."""
    raw = workbooks.load_raw(session, run.version_id, sheet=sheet).sheets[0]
    computed = formula_values(session, run, sheet)
    overrides = overrides_of(run)
    for parent_id in [run.parent_run_id]:
        if parent_id:
            overrides = {**overrides_of(get_run(session, parent_id)), **overrides}
    ov: dict[str, Any] = {}
    for key, value in overrides.items():
        if "!" in key and key.rsplit("!", 1)[0].strip("'") == sheet:
            ov[key.rsplit("!", 1)[1]] = value
    cells: list[dict[str, Any]] = []
    c = raw.cells
    for addr, formula, value, vtype in zip(
        c.address, c.formula, c.value, c.value_type, strict=True
    ):
        if rect is not None:
            r, col = parse_a1_cell(addr)
            if not rect.contains(r, col):
                continue
        if formula is not None:
            if addr in computed:
                v, t = computed[addr]
                cells.append({"address": addr, "value": v, "type": t, "formula": True})
            else:
                cells.append(
                    {"address": addr, "value": value, "type": vtype, "formula": True, "stale": True}
                )
        elif addr in ov:
            v = ov[addr]
            t = (
                "number"
                if isinstance(v, int | float) and not isinstance(v, bool)
                else "bool"
                if isinstance(v, bool)
                else "text"
            )
            cells.append(
                {"address": addr, "value": v, "type": t, "formula": False, "override": True}
            )
        else:
            cells.append({"address": addr, "value": value, "type": vtype, "formula": False})
    return cells


def value_lookup(session: Session, run: Run):
    """Callable (sheet, row, col) -> (value, type) with per-sheet caching, for lineage."""
    cache: dict[str, dict[str, tuple[Any, str]]] = {}

    def lookup(sheet: str, row: int, col: int) -> tuple[Any, str]:
        if sheet not in cache:
            try:
                cells = sheet_values(session, run, sheet)
            except workbooks.SheetNotFoundError:
                cells = []
            cache[sheet] = {cell["address"]: (cell["value"], cell["type"]) for cell in cells}
        from app.model.formula.refs import a1_cell

        return cache[sheet].get(a1_cell(row, col), (None, "empty"))

    return lookup
