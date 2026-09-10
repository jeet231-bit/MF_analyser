import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def _isolated_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Point the app at a throwaway data dir so tests never touch backend/data."""
    data_dir = tmp_path_factory.mktemp("mfa-data")
    os.environ["MFA_DATA_DIR"] = str(data_dir)
    os.environ["MFA_ENVIRONMENT"] = "test"

    from app.config import get_settings
    from app.storage.db import get_engine, get_session_factory

    for cached in (get_settings, get_engine, get_session_factory):
        cached.cache_clear()
    yield data_dir


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
