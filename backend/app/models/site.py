from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Site(Base):
    __tablename__ = "site"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(50), unique=True)
    address: Mapped[str | None] = mapped_column(Text)
    # Sitenin aidat tahakkukunun başladığı ilk dönem (YYYY-MM); daire bazında ezilebilir
    aidat_start_period: Mapped[str | None] = mapped_column(String(7))
    # Takip Excel'i bu dönemden ÖNCESİNİ kapsar; banka ekstresi bu dönemden itibaren işlenir (çift sayım önlemi)
    legacy_cutoff_period: Mapped[str | None] = mapped_column(String(7))
    llm_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_match_threshold: Mapped[float | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    blocks: Mapped[list[Block]] = relationship(
        back_populates="site", cascade="all, delete-orphan", order_by="Block.sort_order"
    )
    bank_accounts: Mapped[list[BankAccount]] = relationship(back_populates="site", cascade="all, delete-orphan")


class BankAccount(Base):
    __tablename__ = "bank_account"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    bank_name: Mapped[str | None] = mapped_column(String(100))
    iban: Mapped[str] = mapped_column(String(34), unique=True)
    account_no: Mapped[str | None] = mapped_column(String(100))
    branch: Mapped[str | None] = mapped_column(String(200))

    site: Mapped[Site] = relationship(back_populates="bank_accounts")


class Block(Base):
    __tablename__ = "block"
    __table_args__ = (UniqueConstraint("site_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(20))
    # Banka açıklamalarında bu bloğu ifade eden ek yazımlar (ör. B bloğu için "b1", "b2"; C1 için "5/1c")
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    site: Mapped[Site] = relationship(back_populates="blocks")
    units: Mapped[list[Unit]] = relationship(
        back_populates="block", cascade="all, delete-orphan", order_by="Unit.number"
    )


class Unit(Base):
    __tablename__ = "unit"
    __table_args__ = (UniqueConstraint("block_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("block.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    room_type: Mapped[str | None] = mapped_column(String(20))
    area_m2: Mapped[float | None] = mapped_column(Numeric(8, 2))
    aidat_start_period: Mapped[str | None] = mapped_column(String(7))
    notes: Mapped[str | None] = mapped_column(Text)
    # Eski Excel'den gelen ve hesaba katılmayan işaretler/notlar ("T B", AV sütunu vb.)
    legacy_tags: Mapped[dict] = mapped_column(JSON, default=dict)

    block: Mapped[Block] = relationship(back_populates="units")
    occupancies: Mapped[list["UnitOccupancy"]] = relationship(  # noqa: F821
        back_populates="unit", cascade="all, delete-orphan"
    )

    @property
    def code(self) -> str:
        return f"{self.block.name}-{self.number}"

    @property
    def site_id(self) -> int:
        return self.block.site_id
