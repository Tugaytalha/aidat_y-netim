from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.site import Unit

IMPORT_KINDS = ("bank_statement", "tracking_excel")
TXN_SOURCES = ("bank", "manual", "legacy_excel")
TXN_STATUSES = ("unmatched", "suggested", "matched", "ignored")
ALLOCATION_CATEGORIES = ("aidat", "demirbas", "asansor", "ek_butce", "diger")
MATCH_METHODS = ("code", "alias", "person", "llm", "manual", "legacy")


class ImportBatch(Base):
    __tablename__ = "import_batch"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    bank_account_id: Mapped[int | None] = mapped_column(ForeignKey("bank_account.id", ondelete="SET NULL"))
    file_name: Mapped[str] = mapped_column(String(300))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    bank_code: Mapped[str | None] = mapped_column(String(30))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    # Takip Excel'i için kesim sonrası değerler (mutabakat raporu) vb.
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BankTransaction(Base):
    __tablename__ = "bank_transaction"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    bank_account_id: Mapped[int | None] = mapped_column(ForeignKey("bank_account.id", ondelete="SET NULL"))
    import_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20), default="bank")
    txn_date: Mapped[date] = mapped_column(Date, index=True)
    # Aynı gün içindeki kronolojik sıra (ekstredeki sıraya göre)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    receipt_no: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    balance_after: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    direction: Mapped[str] = mapped_column(String(3), default="in")
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True)

    payer_name: Mapped[str | None] = mapped_column(String(300))
    sender_bank: Mapped[str | None] = mapped_column(String(200))
    channel: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="unmatched", index=True)
    category_hint: Mapped[str | None] = mapped_column(String(20))
    stated_periods: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Eşleştirme motorunun çıktısı: adaylar, sinyaller, çelişkiler, bölüştürme önerisi
    match_info: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    allocations: Mapped[list[PaymentAllocation]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )


class PaymentAllocation(Base):
    __tablename__ = "payment_allocation"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("bank_transaction.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("unit.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id", ondelete="SET NULL"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    category: Mapped[str] = mapped_column(String(20), default="aidat")
    # Ödemenin yazıldığı ay = gönderildiği ay (işlem tarihi)
    period: Mapped[str] = mapped_column(String(7), index=True)
    method: Mapped[str] = mapped_column(String(20), default="manual")
    confidence: Mapped[float | None] = mapped_column(Float)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(Text)

    transaction: Mapped[BankTransaction] = relationship(back_populates="allocations")
    unit: Mapped[Unit] = relationship()
