import os
import tempfile
from pathlib import Path

# Uygulama modülleri import edilmeden önce test veritabanı ayarlanmalı
_TMP = Path(tempfile.mkdtemp(prefix="aidat_test_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["INITIAL_ADMIN_EMAIL"] = "admin@test.local"
os.environ["INITIAL_ADMIN_PASSWORD"] = "test123"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import Base, SessionLocal, engine  # noqa: E402
import app.models  # noqa: E402,F401

PRIVATE = Path(__file__).parent / "fixtures" / "private"


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    from app.main import app

    with TestClient(app) as c:
        r = c.post("/api/auth/login", data={"username": "admin@test.local", "password": "test123"})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield c


def private_file(name: str) -> Path:
    p = PRIVATE / name
    if not p.exists():
        pytest.skip(f"Özel fikstür yok: {p}")
    return p
