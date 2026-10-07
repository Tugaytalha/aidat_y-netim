from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.site import Unit


class Person(Base):
    __tablename__ = "person"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)

    occupancies: Mapped[list[UnitOccupancy]] = relationship(back_populates="person", cascade="all, delete-orphan")


OCCUPANCY_ROLES = ("owner", "tenant", "payer", "former")


class UnitOccupancy(Base):
    __tablename__ = "unit_occupancy"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("unit.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="owner")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    unit: Mapped[Unit] = relationship(back_populates="occupancies")
    person: Mapped[Person] = relationship(back_populates="occupancies")


ALIAS_MODES = ("single", "split", "ambiguous")
ALIAS_SOURCES = ("manual", "auto", "excel")


class PayerAlias(Base):
    """Öğrenen hafıza: bankadaki gönderen adı -> daire(ler)."""

    __tablename__ = "payer_alias"
    __table_args__ = (UniqueConstraint("site_id", "normalized_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    normalized_name: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(300))
    mode: Mapped[str] = mapped_column(String(20), default="single")
    # [{"unit_id": 5, "ratio": 0.5}, ...]; ambiguous modda ratio yok sayılır
    targets: Mapped[list[dict]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    confirm_count: Mapped[int] = mapped_column(Integer, default=0)
    auto_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
