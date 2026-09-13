"""Settings: the OneDrive guard, the production gate, config-file loading, portable paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import config as config_mod
from app.config import build_settings, onedrive_problem
from app.storage import paths


def test_sync_guard_trips_on_a_path_segment(tmp_path: Path) -> None:
    assert onedrive_problem(tmp_path / "OneDrive - pantomath" / "data")
    assert onedrive_problem(tmp_path / "onedrive" / "x") is not None
    assert onedrive_problem(tmp_path / "MFAnalyser" / "data") is None


def test_sync_guard_trips_under_the_env_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "synced"
    monkeypatch.setenv("OneDrive", str(root))
    assert onedrive_problem(root / "sub" / "data") is not None
    assert onedrive_problem(tmp_path / "elsewhere") is None


def test_startup_refuses_a_synced_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MFA_DATA_DIR", str(tmp_path / "OneDrive - corp" / "data"))
    with pytest.raises(SystemExit, match="OneDrive"):
        build_settings()


def test_production_refuses_to_start_without_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MFA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MFA_ENVIRONMENT", "production")
    monkeypatch.delenv("MFA_AUTH_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("MFA_AUTH_SECRET", raising=False)
    with pytest.raises(SystemExit, match="set_password"):
        build_settings()
    monkeypatch.setenv("MFA_AUTH_PASSWORD_HASH", "pbkdf2_sha256$1$x$y")
    monkeypatch.setenv("MFA_AUTH_SECRET", "s")
    settings = build_settings()
    assert settings.is_production and settings.auth_enabled


def test_config_file_is_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.env"
    cfg.write_text(f"MFA_DATA_DIR={tmp_path / 'from-file'}\nMFA_PORT=8123\n", encoding="utf-8")
    monkeypatch.delenv("MFA_DATA_DIR", raising=False)
    monkeypatch.setenv("MFA_CONFIG_FILE", str(cfg))
    settings = build_settings()
    assert settings.data_dir == tmp_path / "from-file"
    assert settings.port == 8123
    assert settings.resolved_backup_dir == tmp_path / "backups"
    assert settings.resolved_log_dir == tmp_path / "from-file" / "logs"


def test_default_data_dir_is_outside_the_repo() -> None:
    default = config_mod.Settings.model_fields["data_dir"].default
    assert config_mod.REPO_ROOT not in Path(default).parents


def test_stored_paths_are_relative_and_rebase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    data_dir = get_settings().data_dir
    inside = data_dir / "workbooks" / "v1" / "master.xlsx"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_bytes(b"x")
    assert paths.to_stored(inside) == "workbooks/v1/master.xlsx"
    assert paths.resolve_stored("workbooks/v1/master.xlsx") == inside
    # An old row holding an absolute path under a directory that no longer exists.
    old = str(tmp_path / "gone" / "data" / "workbooks" / "v1" / "master.xlsx")
    assert paths.resolve_stored(old) == inside
    assert paths.resolve_stored("workbooks/v9/missing.xlsx") is None
    assert paths.resolve_stored(None) is None
    outside = tmp_path / "samples" / "m.xlsx"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"x")
    assert Path(paths.to_stored(outside)).is_absolute()
    assert paths.resolve_stored(paths.to_stored(outside)) == outside.resolve()
