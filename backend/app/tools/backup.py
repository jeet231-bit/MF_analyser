"""Daily backup: a consistent copy of the SQLite database (SQLite's online backup API, which is
safe while the service runs and under WAL) plus the uploaded workbooks, into a dated folder;
folders older than the retention window are removed. With a mirror, the newest dated folder is
then copied off the machine (a share or a synced folder), where the last four weekly copies
are kept, so a dead disk does not take the history with it.

    python -m app.tools.backup [--data-dir ...] [--backup-dir ...] [--keep 30]
                               [--mirror \\\\server\\share\\mfa | --no-mirror] [--keep-weeks 4]
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
MANIFEST = "manifest.json"


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


def dated_folders(root: Path) -> list[tuple[date, Path]]:
    """The ``YYYY-MM-DD`` folders under ``root``, oldest first; anything else is left alone."""
    out: list[tuple[date, Path]] = []
    if not root.is_dir():
        return out
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            out.append((date.fromisoformat(child.name), child))
        except ValueError:
            continue
    return sorted(out)


def prune(backup_dir: Path, keep_days: int, today: date | None = None) -> list[Path]:
    """Remove dated folders older than ``keep_days``."""
    today = today or date.today()
    cutoff = today - timedelta(days=keep_days)
    removed: list[Path] = []
    for stamp, child in dated_folders(backup_dir):
        if stamp < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child)
    return removed


def _weeks_between(week: tuple[int, int], later: tuple[int, int]) -> int:
    a = date.fromisocalendar(week[0], week[1], 1)
    b = date.fromisocalendar(later[0], later[1], 1)
    return (b - a).days // 7


def prune_weekly(mirror_dir: Path, keep_weeks: int, today: date | None = None) -> list[Path]:
    """Keep one folder per ISO week (the newest of that week) for the last ``keep_weeks``
    weeks, counting the current week; remove every other dated folder."""
    today = today or date.today()
    this_week = today.isocalendar()[:2]
    newest_per_week: dict[tuple[int, int], Path] = {}
    for _stamp, child in dated_folders(mirror_dir):
        newest_per_week[_stamp.isocalendar()[:2]] = child
    kept_weeks = [
        w
        for w in sorted(newest_per_week, reverse=True)
        if _weeks_between(w, this_week) < keep_weeks
    ]
    keep = {newest_per_week[w] for w in kept_weeks[:keep_weeks]}
    removed: list[Path] = []
    for _stamp, child in dated_folders(mirror_dir):
        if child not in keep:
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child)
    return removed


def mirror_backup(
    dest: Path, mirror_dir: Path, keep_weeks: int = 4, today: date | None = None
) -> dict[str, object]:
    """Copy the dated folder ``dest`` into ``mirror_dir`` and apply the weekly retention."""
    today = today or date.today()
    try:
        mirror_dir.mkdir(parents=True, exist_ok=True)
        copied = mirror_tree(dest, mirror_dir / dest.name)
        removed = prune_weekly(mirror_dir, keep_weeks, today)
    except OSError as exc:
        return {"path": str(mirror_dir), "status": "unreachable", "error": str(exc)}
    return {
        "path": str(mirror_dir),
        "status": "ok",
        "files_copied": copied,
        "removed": [p.name for p in removed],
        "copies": [p.name for _d, p in dated_folders(mirror_dir)],
        "keep_weeks": keep_weeks,
    }


def backup(
    data_dir: Path,
    backup_dir: Path,
    keep_days: int = 30,
    today: date | None = None,
    mirror_dir: Path | None = None,
    keep_weeks: int = 4,
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
    workbook_files = (
        sum(1 for p in (dest / WORKBOOKS).rglob("*") if p.is_file())
        if (dest / WORKBOOKS).exists()
        else 0
    )
    manifest: dict[str, object] = {
        "taken_at": datetime.now(UTC).isoformat(),
        "data_dir": str(data_dir),
        "database_bytes": (dest / DB_NAME).stat().st_size if (dest / DB_NAME).exists() else 0,
        "versions": versions,
        "workbook_files_copied": copied,
        "workbook_files_total": workbook_files,
        "keep_days": keep_days,
        "mirror": None,
    }
    (dest / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    prune(backup_dir, keep_days, today)
    if mirror_dir is not None:
        manifest["mirror"] = mirror_backup(dest, mirror_dir, keep_weeks, today)
        (dest / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        # The mirror keeps its own manifest so a restore from the mirror is self-describing.
        try:
            shutil.copy2(dest / MANIFEST, mirror_dir / dest.name / MANIFEST)
        except OSError:
            pass
    return dest


def main(argv: list[str] | None = None) -> int:
    from app.config import get_settings

    parser = argparse.ArgumentParser(description="Back up the MF Analyser database and workbooks.")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--keep", type=int, default=30, help="days of dated folders to keep")
    parser.add_argument(
        "--mirror",
        type=Path,
        help="off-machine folder for the newest backup (default: MFA_BACKUP_MIRROR)",
    )
    parser.add_argument(
        "--no-mirror", action="store_true", help="skip the mirror even when one is configured"
    )
    parser.add_argument(
        "--keep-weeks", type=int, default=4, help="weekly copies to keep on the mirror"
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    data_dir = args.data_dir or settings.data_dir
    backup_dir = args.backup_dir or settings.resolved_backup_dir
    mirror_dir = None if args.no_mirror else (args.mirror or settings.backup_mirror)
    dest = backup(
        data_dir, backup_dir, args.keep, mirror_dir=mirror_dir, keep_weeks=args.keep_weeks
    )
    manifest = json.loads((dest / MANIFEST).read_text(encoding="utf-8"))
    print(
        f"backup written to {dest}: {manifest['versions']} versions, "
        f"{manifest['workbook_files_total']} workbook files"
    )
    mirror = manifest.get("mirror")
    if mirror is None:
        print(
            "WARNING: no backup mirror is configured (MFA_BACKUP_MIRROR); this backup sits on the "
            "same disk as the data and will not survive a drive failure.",
            file=sys.stderr,
        )
        return 0
    if mirror["status"] != "ok":
        print(
            f"WARNING: mirror {mirror['path']} is unreachable: {mirror['error']}", file=sys.stderr
        )
        return 3
    print(f"mirrored to {mirror['path']}: copies kept {', '.join(mirror['copies'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
