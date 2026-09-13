"""Application settings. Every value can be overridden with an ``MFA_`` environment variable,
from ``backend/.env`` in development, or from the production config file (``MFA_CONFIG_FILE``,
default ``C:\\MFAnalyser\\config.env``) that the installer writes."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
# Data lives outside the working tree and outside any synced folder: a synced SQLite file
# gets locked and corrupted by the sync client.
DEFAULT_ROOT = (
    Path(r"C:\MFAnalyser") if os.name == "nt" else Path.home() / ".local" / "share" / "mf-analyser"
)
DEFAULT_CONFIG_FILE = DEFAULT_ROOT / "config.env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MFA_", env_file=".env", extra="ignore")

    app_name: str = "mf-analyser"
    environment: str = "development"  # development | test | production
    data_dir: Path = DEFAULT_ROOT / "data"
    backup_dir: Path | None = None  # default: <data root>/backups
    log_dir: Path | None = None  # default: <data_dir>/logs
    static_dir: Path | None = None  # default: <repo>/frontend/dist when it exists
    database_url: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    max_upload_mb: int = 50
    # Alternative dashboard.config.json (tests, deployments); empty = the repo-root file.
    dashboard_config_path: str = ""
    # Engine concurrency on this (single-process) backend: each live engine state is ~300 MB
    # on the real master, so runs are serialised and only a few states stay cached.
    max_concurrent_runs: int = 1
    run_busy_retry_after_s: int = 3
    state_cache_entries: int = 3
    # Validation gate thresholds (fractions of checked formula cells).
    validation_max_mismatch_ratio: float = 0.0
    validation_max_precision_ratio: float = 0.001
    # The access gate: one shared password (a pbkdf2_sha256 hash written by
    # `python -m app.tools.set_password`) and a secret that signs the session cookie.
    # No hash means no gate outside production; production refuses to start without both.
    auth_password_hash: str = ""
    auth_secret: str = ""
    session_hours: int = 12

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'mf-analyser.db').as_posix()}"

    @property
    def resolved_backup_dir(self) -> Path:
        return self.backup_dir or self.data_dir.parent / "backups"

    @property
    def resolved_log_dir(self) -> Path:
        return self.log_dir or self.data_dir / "logs"

    @property
    def resolved_static_dir(self) -> Path | None:
        if self.static_dir is not None:
            return self.static_dir
        default = REPO_ROOT / "frontend" / "dist"
        return default if (default / "index.html").exists() else None

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def auth_enabled(self) -> bool:
        return bool(self.auth_password_hash)


def onedrive_problem(path: Path) -> str | None:
    """Why ``path`` must not hold the database: inside a OneDrive folder, or None."""
    resolved = Path(os.path.abspath(path))
    if any("onedrive" in part.lower() for part in resolved.parts):
        return f"{resolved} is inside a OneDrive folder"
    for var in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        root = os.environ.get(var)
        if not root:
            continue
        try:
            resolved.relative_to(Path(os.path.abspath(root)))
        except ValueError:
            continue
        return f"{resolved} is under the OneDrive folder {root}"
    return None


def config_file() -> Path | None:
    """The production config file: ``MFA_CONFIG_FILE`` when set, else the default when present."""
    explicit = os.environ.get("MFA_CONFIG_FILE")
    if explicit:
        return Path(explicit)
    return DEFAULT_CONFIG_FILE if DEFAULT_CONFIG_FILE.exists() else None


def build_settings() -> Settings:
    """Load settings and refuse a layout that would corrupt the data or expose it."""
    extra = config_file()
    settings = Settings(_env_file=(".env", str(extra)) if extra else ".env")  # type: ignore[call-arg]
    for label, path in (
        ("data directory", settings.data_dir),
        ("backup directory", settings.resolved_backup_dir),
    ):
        problem = onedrive_problem(path)
        if problem:
            raise SystemExit(
                f"Refusing to start: the {label} {problem}. OneDrive sync locks and corrupts an "
                f"open SQLite file. Set MFA_DATA_DIR (or -DataDir in deploy\\install.ps1) to a "
                f"local folder such as {DEFAULT_ROOT / 'data'}."
            )
    if settings.is_production and not (settings.auth_password_hash and settings.auth_secret):
        raise SystemExit(
            "Refusing to start in production without the access gate: set the shared password "
            "with `python -m app.tools.set_password` (it writes MFA_AUTH_PASSWORD_HASH and "
            "MFA_AUTH_SECRET into the config file) and restart."
        )
    return settings


@lru_cache
def get_settings() -> Settings:
    settings = build_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
