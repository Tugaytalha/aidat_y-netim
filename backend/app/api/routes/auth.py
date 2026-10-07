from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DB, Admin, CurrentUser, audit
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User, UserSite

router = APIRouter(prefix="/api", tags=["auth"])


def user_out(u: User, site_ids: list[int] | None = None) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active,
            "site_ids": site_ids}


@router.post("/auth/login")
def login(db: DB, form: OAuth2PasswordRequestForm = Depends()):
    user = db.scalar(select(User).where(User.email == form.username.strip().lower()))
    if not user or not user.is_active or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-posta veya şifre hatalı")
    return {"access_token": create_access_token(user.id), "token_type": "bearer", "user": user_out(user)}


@router.get("/auth/me")
def me(user: CurrentUser):
    return user_out(user)


class UserIn(BaseModel):
    email: str
    full_name: str = ""
    password: str
    role: str = "operator"
    site_ids: list[int] = []


class UserPatch(BaseModel):
    full_name: str | None = None
    password: str | None = None
    role: str | None = None
    is_active: bool | None = None
    site_ids: list[int] | None = None


@router.get("/users")
def list_users(db: DB, _: Admin):
    out = []
    for u in db.scalars(select(User).order_by(User.id)):
        out.append(user_out(u, list(db.scalars(select(UserSite.site_id).where(UserSite.user_id == u.id)))))
    return out


@router.post("/users", status_code=201)
def create_user(body: UserIn, db: DB, admin: Admin):
    if body.role not in ("admin", "operator", "viewer"):
        raise HTTPException(400, "Geçersiz rol")
    email = body.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Bu e-posta zaten kayıtlı")
    u = User(email=email, full_name=body.full_name, password_hash=hash_password(body.password), role=body.role)
    db.add(u)
    db.flush()
    for sid in body.site_ids:
        db.add(UserSite(user_id=u.id, site_id=sid))
    audit(db, admin, "create", "user", u.id, data={"email": email, "role": body.role})
    db.commit()
    return user_out(u, body.site_ids)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, db: DB, admin: Admin):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Kullanıcı bulunamadı")
    if body.full_name is not None:
        u.full_name = body.full_name
    if body.password:
        u.password_hash = hash_password(body.password)
    if body.role is not None:
        u.role = body.role
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.site_ids is not None:
        for us in db.scalars(select(UserSite).where(UserSite.user_id == u.id)):
            db.delete(us)
        db.flush()
        for sid in body.site_ids:
            db.add(UserSite(user_id=u.id, site_id=sid))
    audit(db, admin, "update", "user", u.id, data=body.model_dump(exclude={"password"}, exclude_none=True))
    db.commit()
    return user_out(u, list(db.scalars(select(UserSite.site_id).where(UserSite.user_id == u.id))))
