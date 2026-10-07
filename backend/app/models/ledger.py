from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.site import Unit

TARIFF_SCOPES = ("site", "room_type", "unit")
CHARGE_TYPES = ("aidat", "demirbas", "asansor", "ek_butce", "devir", "duzeltme")


class Tariff(Base):
    __tablename__ = "tariff"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(20), default="site")
    # room_type için tip adı ("3+1"), unit için unit id (metin olarak)
    scope_value: Mapped[str | None] = mapped_column(String(50))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    valid_from: Mapped[str] = mapped_column(String(7))
    valid_to: Mapped[str | None] = mapped_column(String(7))
    note: Mapped[str | None] = mapped_column(Text)


class ChargeBatch(Base):
    """Tek seferlik toplu tahakkuk (ör. şifrematik demirbaş 2000 TL, tüm daireler)."""

    __tablename__ = "charge_batch"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(20))
    period: Mapped[str] = mapped_column(String(7))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    description: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Charge(Base):
    __tablename__ = "charge"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("unit.id", ondelete="CASCADE"), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    type: Mapped[str] = mapped_column(String(20), default="aidat")
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    description: Mapped[str | None] = mapped_column(Text)
    # auto | manual | batch | opening
    source: Mapped[str] = mapped_column(String(20), default="auto")
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("charge_batch.id", ondelete="CASCADE"))
    # Aylık aidat için "aidat:{unit_id}:{period}" -> aynı ay iki kez tahakkuk edilemez
    unique_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    unit: Mapped[Unit] = relationship()


class PeriodLock(Base):
    __tablename__ = "period_lock"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), unique=True)
    # Bu dönem (dahil) ve öncesi kilitli
    locked_until: Mapped[str] = mapped_column(String(7))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    revision: Mapped[int] = mapped_column(Integer, default=1)
