"""Persistence of engine runs and composition of their values on read."""

from __future__ import annotations

import gzip
import json
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.engine.runner import Engine, RunResult, RunSummary, resolve_override
from app.engine.values import StringTable, Values
from app.model.formula.refs import Rect, parse_a1_cell
from app.model.schema import WorkbookLogicModel
from app.parser.models import RawWorkbook
from app.storage import logic, workbooks
from app.storage.models import Run, RunSheetValues, WorkbookVersion


class RunNotFoundError(LookupError):
    pass


class RunBusyError(RuntimeError):
    """Another engine run holds the limiter; the caller should retry shortly."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__("another run is in progress")
        self.retry_after_s = retry_after_s


class _RunLimiter:
    """At most ``max_concurrent_runs`` engine runs at a time (each holds ~300 MB of grids on
    the real master). A run that cannot start at once is refused with RunBusyError rather
    than queued invisibly, so the UI can show "another run is in progress" and retry."""

    def __init__(self) -> None:
        self._sem: threading.BoundedSemaphore | None = None
        self._size = 0
        self._guard = threading.Lock()

    def _semaphore(self) -> threading.BoundedSemaphore:
        size = max(1, get_settings().max_concurrent_runs)
        with self._guard:
            if self._sem is None or self._size != size:
                self._sem = threading.BoundedSemaphore(size)
                self._size = size
            return self._sem

    def acquire(self, wait_s: float = 0.25) -> None:
        if not self._semaphore().acquire(timeout=wait_s):
            raise RunBusyError(get_settings().run_busy_retry_after_s)

    def release(self) -> None:
        try:
            self._semaphore().release()
        except ValueError:  # released more than acquired; never fatal
            pass


run_limiter = _RunLimiter()


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
    """In-process cache of runs' final grids: baselines seed incremental runs without
    reloading, and any cached run can explain its cells (lineage traces)."""

    def __init__(self, capacity: int | None = None) -> None:
        self._capacity = capacity
        self._items: dict[tuple[str, str], tuple[dict, Any]] = {}
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        if self._capacity is not None:
            return self._capacity
        return max(1, get_settings().state_cache_entries)

    def get(self, key: tuple[str, str]):
        with self._lock:
            item = self._items.get(key)
            if item is not None:  # most recently used goes last
                self._items.pop(key)
                self._items[key] = item
            return item

    def put(self, key: tuple[str, str], value) -> None:
        with self._lock:
            self._items.pop(key, None)
            self._items[key] = value
            while len(self._items) > self.capacity:
                self._items.pop(next(iter(self._items)))

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


state_cache = _StateCache()


def create_run(
    session: Session, version_id: str, overrides: dict[str, Any] | None, mode: str = "auto"
) -> Run:
    """Execute and persist a run. The first override-free full run becomes the baseline.
    Raises RunBusyError when the run limiter is held by another run."""
    engine, model, _meta, version = load_engine(session, version_id)
    overrides = overrides or {}
    parent = baseline_run(session, version_id) if overrides and mode != "full" else None
    run_limiter.acquire()
    try:
        if parent is not None:
            # The baseline's grids are rebuilt once after a restart and then cloned per what-if.
            result = engine.run(overrides, mode=mode, state=state_for(session, parent))
        else:
            result = engine.run(overrides, mode=mode)
        run = save_run(
            session, version, result, parent_run_id=parent.id if parent is not None else None
        )
        state_cache.put((version_id, run.id), (result.grids, result.table))
    finally:
        run_limiter.release()
    return run


_rebuild_lock = threading.Lock()


def state_for(session: Session, run: Run) -> tuple[dict, Any]:
    """The run's final grids and string table: from the in-process cache, or rebuilt once from
    the stored values (parent chain composed, overrides applied) and cached."""
    cached = state_cache.get((run.version_id, run.id))
    if cached is not None:
        return cached
    with _rebuild_lock:  # two callers must not rebuild the same 300 MB state side by side
        cached = state_cache.get((run.version_id, run.id))
        if cached is not None:
            return cached
        return _rebuild_state(session, run)


def _rebuild_state(session: Session, run: Run) -> tuple[dict, Any]:
    engine, _model, _meta, _version = load_engine(session, run.version_id)
    chain: list[Run] = []
    current: Run | None = run
    while current is not None:
        chain.append(current)
        current = session.get(Run, current.parent_run_id) if current.parent_run_id else None
    merged: dict[str, dict[str, tuple[Any, str]]] = {}
    for r in reversed(chain):
        for blob in r.sheets:
            cols = _unpack(blob.payload)
            target = merged.setdefault(blob.sheet_name, {})
            for addr, value, vtype in zip(
                cols["address"], cols["value"], cols["type"], strict=True
            ):
                target[addr] = (value, vtype)
    seed = {
        sheet: {
            "address": list(cells),
            "value": [v for v, _t in cells.values()],
            "type": [t for _v, t in cells.values()],
        }
        for sheet, cells in merged.items()
    }
    table = StringTable()
    grids = engine.load_state(table, seed)
    overrides: dict[str, Any] = {}
    for r in reversed(chain):
        overrides.update(overrides_of(r))
    for key, value in overrides.items():
        sheet, row, col = resolve_override(key, engine.meta, engine.model)
        if sheet in grids:
            grids[sheet].write(Rect.cell(row, col), Values.from_python(value, table))
    state = (grids, table)
    state_cache.put((run.version_id, run.id), state)
    return state


def start_background_run(
    session: Session, version_id: str, overrides: dict[str, Any] | None, mode: str = "auto"
) -> Run:
    """Create a ``running`` run row and execute it on a thread with its own session; the row
    turns ``ok`` (with values) or ``failed`` (with ``error``). Poll ``get_run`` for progress."""
    from app.storage.db import get_session_factory

    workbooks.get_version(session, version_id)
    logic.get_model(session, version_id)  # fail fast when there is nothing to run
    run = Run(
        id=uuid.uuid4().hex,
        version_id=version_id,
        kind="full" if mode == "full" or not overrides else "incremental",
        parent_run_id=None,
        overrides_json=json.dumps(overrides or {}, sort_keys=True),
        status="running",
        summary_json=RunSummary(
            kind=mode,
            blocks_evaluated=0,
            cells_evaluated=0,
            seconds=0.0,
            peak_mb=0.0,
            error_cells=0,
        ).model_dump_json(),
        created_at=datetime.now(UTC),
    )
    session.add(run)
    session.commit()
    run_id = run.id
    factory = get_session_factory()

    def work() -> None:
        with factory() as s:
            row = s.get(Run, run_id)
            try:
                run_limiter.acquire(wait_s=3600)  # background jobs wait their turn
            except RunBusyError as exc:
                if row is not None:
                    row.status = "failed"
                    row.error = f"RunBusyError: {exc}"
                    s.commit()
                return
            try:
                engine, _model, _meta, version = load_engine(s, version_id)
                ov = overrides or {}
                parent = baseline_run(s, version_id) if ov and mode != "full" else None
                if parent is not None and parent.id != run_id:
                    result = engine.run(ov, mode=mode, state=state_for(s, parent))
                else:
                    result = engine.run(ov, mode=mode)
                save_run(s, version, result, parent_run_id=parent.id if parent else None, row=row)
                state_cache.put((version_id, run_id), (result.grids, result.table))
            except Exception as exc:  # noqa: BLE001 - reported on the row, never raised here
                s.rollback()
                row = s.get(Run, run_id)
                if row is not None:
                    row.status = "failed"
                    row.error = f"{type(exc).__name__}: {exc}"
                    s.commit()
            finally:
                run_limiter.release()

    threading.Thread(target=work, name=f"run-{run_id[:8]}", daemon=True).start()
    return run


def save_run(
    session: Session,
    version: WorkbookVersion,
    result: RunResult,
    *,
    parent_run_id: str | None,
    row: Run | None = None,
) -> Run:
    run = row or Run(id=uuid.uuid4().hex, version_id=version.id, created_at=datetime.now(UTC))
    run.kind = result.kind
    run.parent_run_id = parent_run_id
    run.overrides_json = json.dumps(result.overrides, sort_keys=True)
    run.status = "ok"
    run.error = None
    run.summary_json = result.summary.model_dump_json()
    if row is None:
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
