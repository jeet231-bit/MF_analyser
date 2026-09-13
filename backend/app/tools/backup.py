"""Daily backup: a consistent copy of the SQLite database (SQLite's online backup API, which is
safe while the service runs and under WAL) plus the uploaded workbooks, into a dated folder;
folders older than the retention window are removed.

    python -m app.tools.backup [--data-dir ...] [--backup-dir ...] [--keep 30]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

DB_NAME = "mf-analyser.db"
WORKBOOKS = "workbooks"


def backup_database(src: Path, dst: Path) -> None:
    """Copy a live SQLite database with the backup API (never a file copy)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    source = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        target = sqlite3.connect(dst)
        try:
            source.backup(target, pages=1024)
        finally:
            target.close()
    finally:
        source.close()


def mirror_tree(src: Path, dst: Path) -> int:
    """Copy files under ``src`` into ``dst`` unless already present at the same size."""
    copied = 0
    if not src.is_dir():
        return 0
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        target = dst / path.relative_to(src)
        if target.exists() and target.stat().st_size == path.stat().st_size:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    return copied


def prune(backup_dir: Path, keep_days: int, today: date | None = None) -> list[Path]:
    """Remove dated folders older than ``keep_days``; folders not named YYYY-MM-DD are left alone."""
    today = today or date.today()
    cutoff = today - timedelta(days=keep_days)
    removed: list[Path] = []
    if not backup_dir.is_dir():
        return removed
    for child in backup_dir.iterdir():
        if not child.is_dir():
            continue
        try:
            stamp = date.fromisoformat(child.name)
        except ValueError:
            continue
        if stamp < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child)
    return removed


def backup(
    data_dir: Path, backup_dir: Path, keep_days: int = 30, today: date | None = None
) -> Path:
    today = today or date.today()
    dest = backup_dir / today.isoformat()
    dest.mkdir(parents=True, exist_ok=True)
    db = data_dir / DB_NAME
    if db.exists():
        backup_database(db, dest / DB_NAME)
    copied = mirror_tree(data_dir / WORKBOOKS, dest / WORKBOOKS)
    versions = 0
    if (dest / DB_NAME).exists():
        conn = sqlite3.connect(dest / DB_NAME)
        try:
            versions = conn.execute("SELECT COUNT(*) FROM workbook_versions").fetchone()[0]
        except sqlite3.Error:
            versions = 0
        finally:
            conn.close()
    manifest = {
        "taken_at": datetime.now(UTC).isoformat(),
        "data_dir": str(data_dir),
        "database_bytes": (dest / DB_NAME).stat().st_size if (dest / DB_NAME).exists() else 0,
        "versions": versions,
        "workbook_files_copied": copied,
        "workbook_files_total": sum(1 for p in (dest / WORKBOOKS).rglob("*") if p.is_file())
        if (dest / WORKBOOKS).exists()
        else 0,
        "keep_days": keep_days,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    prune(backup_dir, keep_days, today)
    return dest


def main(argv: list[str] | None = None) -> int:
    from app.config import get_settings

    parser = argparse.ArgumentParser(description="Back up the MF Analyser database and workbooks.")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--keep", type=int, default=30, help="days of dated folders to keep")
    args = parser.parse_args(argv)
    settings = get_settings()
    data_dir = args.data_dir or settings.data_dir
    backup_dir = args.backup_dir or settings.resolved_backup_dir
    dest = backup(data_dir, backup_dir, args.keep)
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    print(
        f"backup written to {dest}: {manifest['versions']} versions, {manifest['workbook_files_total']} workbook files"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
