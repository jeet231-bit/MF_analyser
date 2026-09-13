"""Restore a dated backup over the data directory. Stop the service first: the restore refuses
to run while another process holds the database.

    python -m app.tools.restore YYYY-MM-DD [--data-dir ...] [--backup-dir ...]
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

from app.tools.backup import DB_NAME, WORKBOOKS, mirror_tree


class RestoreRefusedError(RuntimeError):
    pass


def _ensure_unlocked(db: Path) -> None:
    if not db.exists():
        return
    try:
        conn = sqlite3.connect(db, timeout=1, isolation_level=None)
        try:
            conn.execute("PRAGMA locking_mode=EXCLUSIVE")
            conn.execute("BEGIN EXCLUSIVE")
            conn.execute("ROLLBACK")
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        raise RestoreRefusedError(
            f"the database at {db} is in use ({exc}); stop the MFAnalyser service and retry"
        ) from exc


def restore(backup_dir: Path, stamp: str, data_dir: Path) -> dict[str, int]:
    src = backup_dir / stamp
    if not (src / DB_NAME).exists():
        raise RestoreRefusedError(f"no backup at {src}")
    live = data_dir / DB_NAME
    _ensure_unlocked(live)
    data_dir.mkdir(parents=True, exist_ok=True)
    for stale in (live, live.with_name(live.name + "-wal"), live.with_name(live.name + "-shm")):
        if stale.exists():
            stale.unlink()
    shutil.copy2(src / DB_NAME, live)
    copied = mirror_tree(src / WORKBOOKS, data_dir / WORKBOOKS)
    conn = sqlite3.connect(live)
    try:
        versions = conn.execute("SELECT COUNT(*) FROM workbook_versions").fetchone()[0]
    finally:
        conn.close()
    return {"versions": versions, "workbook_files_copied": copied}


def main(argv: list[str] | None = None) -> int:
    from app.config import get_settings

    parser = argparse.ArgumentParser(
        description="Restore an MF Analyser backup (stop the service first)."
    )
    parser.add_argument("date", help="the dated backup folder, YYYY-MM-DD")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args(argv)
    settings = get_settings()
    try:
        result = restore(
            args.backup_dir or settings.resolved_backup_dir,
            args.date,
            args.data_dir or settings.data_dir,
        )
    except RestoreRefusedError as exc:
        print(f"restore refused: {exc}", file=sys.stderr)
        return 2
    print(
        f"restored {args.date}: {result['versions']} versions, {result['workbook_files_copied']} workbook files copied"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
