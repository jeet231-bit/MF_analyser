"""Operations: SQLite pragmas, the backup tool, pruning, and the restore drill."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import get_settings
from app.storage.db import get_engine
from app.tools import backup as backup_tool
from app.tools import restore as restore_tool
from tests.fixtures.workbook import fixture_xlsx_bytes


def test_sqlite_runs_in_wal_mode_with_a_busy_timeout(client: TestClient) -> None:
    with get_engine().connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 5000
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def _upload(client: TestClient, tmp_path: Path, name: str = "master.xlsx") -> str:
    del tmp_path
    response = client.post(
        "/api/workbooks", files={"file": (name, fixture_xlsx_bytes(), "application/octet-stream")}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_backup_is_consistent_while_the_app_holds_the_database(
    client: TestClient, tmp_path: Path
) -> None:
    version_id = _upload(client, tmp_path)
    settings = get_settings()
    backup_dir = tmp_path / "backups"
    with get_engine().connect() as held:  # an open connection, as the service always has
        held.execute(text("SELECT COUNT(*) FROM workbook_versions"))
        dest = backup_tool.backup(
            settings.data_dir, backup_dir, keep_days=30, today=date(2026, 9, 13)
        )
    assert dest == backup_dir / "2026-09-13"
    copy = sqlite3.connect(dest / "mf-analyser.db")
    ids = {row[0] for row in copy.execute("SELECT id FROM workbook_versions")}
    copy.close()
    assert version_id in ids
    assert (dest / "workbooks" / version_id / "master.xlsx").exists()
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["versions"] == len(ids) and manifest["workbook_files_total"] >= 1


def test_prune_keeps_the_retention_window(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    today = date(2026, 9, 13)
    for days_ago in range(0, 45):
        (backup_dir / (today - timedelta(days=days_ago)).isoformat()).mkdir(parents=True)
    (backup_dir / "keep-me").mkdir()
    removed = backup_tool.prune(backup_dir, keep_days=30, today=today)
    assert len(removed) == 14  # 31..44 days old
    remaining = sorted(p.name for p in backup_dir.iterdir())
    assert len(remaining) == 31 + 1 and "keep-me" in remaining
    assert (today - timedelta(days=30)).isoformat() in remaining
    assert (today - timedelta(days=31)).isoformat() not in remaining


def test_restore_round_trip(client: TestClient, tmp_path: Path) -> None:
    version_id = _upload(client, tmp_path)
    settings = get_settings()
    backup_dir = tmp_path / "backups"
    stamp = "2026-09-13"
    backup_tool.backup(settings.data_dir, backup_dir, today=date(2026, 9, 13))

    # Restore refuses while the app holds the database ...
    with get_engine().connect() as held:
        held.execute(text("BEGIN IMMEDIATE"))
        with pytest.raises(restore_tool.RestoreRefusedError, match="in use"):
            restore_tool.restore(backup_dir, stamp, settings.data_dir)
        held.execute(text("ROLLBACK"))
    # ... and refuses an unknown date.
    with pytest.raises(restore_tool.RestoreRefusedError, match="no backup"):
        restore_tool.restore(backup_dir, "1999-01-01", settings.data_dir)

    # Simulate a lost data directory: the service is stopped and the files are gone.
    get_engine().dispose()
    db = settings.data_dir / "mf-analyser.db"
    for stale in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
        if stale.exists():
            stale.unlink()
    workbook = settings.data_dir / "workbooks" / version_id / "master.xlsx"
    workbook.unlink()

    result = restore_tool.restore(backup_dir, stamp, settings.data_dir)
    assert result["versions"] >= 1 and result["workbook_files_copied"] == 1
    assert workbook.exists()
    listed = {v["id"] for v in client.get("/api/workbooks").json()}
    assert version_id in listed
    assert client.get(f"/api/workbooks/{version_id}").status_code == 200
