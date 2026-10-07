from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.routes import auth, imports, ledger, people, reports, sites, transactions
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import User


def ensure_admin() -> None:
    """Kullanıcı tablosu boşsa ilk yöneticiyi oluşturur."""
    s = get_settings()
    with SessionLocal() as db:
        if db.scalar(select(User).limit(1)) is None:
            db.add(User(email=s.initial_admin_email.lower(), full_name="Yönetici",
                        password_hash=hash_password(s.initial_admin_password), role="admin"))
            db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_admin()
    yield


app = FastAPI(title="Ortabahçe Aidat Yönetimi", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

for r in (auth, sites, people, ledger, imports, transactions, reports):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
