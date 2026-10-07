from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_token
from app.models import AuditLog, Site, User, UserSite

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

DB = Annotated[Session, Depends(get_db)]


def current_user(db: DB, token: Annotated[str | None, Depends(oauth2)]) -> User:
    uid = decode_token(token) if token else None
    user = db.get(User, uid) if uid else None
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Oturum geçersiz", headers={"WWW-Authenticate": "Bearer"})
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_writer(user: CurrentUser) -> User:
    if user.role not in ("admin", "operator"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bu işlem için yetkiniz yok")
    return user


def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sadece yönetici yapabilir")
    return user


Writer = Annotated[User, Depends(require_writer)]
Admin = Annotated[User, Depends(require_admin)]


def accessible_site_ids(db: Session, user: User) -> set[int] | None:
    """None = tüm siteler (admin)."""
    if user.role == "admin":
        return None
    return set(db.scalars(select(UserSite.site_id).where(UserSite.user_id == user.id)))


def get_site(db: Session, user: User, site_id: int) -> Site:
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site bulunamadı")
    allowed = accessible_site_ids(db, user)
    if allowed is not None and site_id not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bu siteye erişiminiz yok")
    return site


def audit(db: Session, user: User | None, action: str, entity: str, entity_id: int | None = None,
          site_id: int | None = None, data: dict | None = None) -> None:
    db.add(AuditLog(user_id=user.id if user else None, site_id=site_id, action=action, entity=entity,
                    entity_id=entity_id, data=data or {}))
