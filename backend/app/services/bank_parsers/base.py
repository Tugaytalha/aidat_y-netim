"""Banka ekstresi ayrıştırıcı arayüzü ve ortak tablo okuma mantığı."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.services.common import parse_tr_date, parse_tr_number
from app.services.xlsx.reader import Rows, read_workbook


@dataclass
class ParsedTransaction:
    txn_date: date
    receipt_no: str | None
    description: str
    amount: Decimal
    balance_after: Decimal | None
    row_index: int  # dosyadaki satır (0 tabanlı)
    seq: int = 0  # aynı gün içindeki kronolojik sıra


@dataclass
class ParsedStatement:
    bank_code: str
    bank_name: str
    account_holder: str | None = None
    iban: str | None = None
    account_no: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    transactions: list[ParsedTransaction] = field(default_factory=list)
    footer_credit_total: Decimal | None = None
    footer_debit_total: Decimal | None = None
    warnings: list[str] = field(default_factory=list)


class StatementParseError(Exception):
    pass


def _cell_text(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _fold(s: str) -> str:
    from app.services.matching.normalize import fold

    return fold(s)


# Başlık eş anlamlıları (katlanmış/küçük harf)
COLUMN_SYNONYMS = {
    "date": ("tarih", "islem tarihi", "valor"),
    "receipt": ("fis no", "fis", "dekont no", "referans", "islem no"),
    "description": ("aciklama", "islem aciklamasi"),
    "amount": ("islem tutari", "tutar"),
    "balance": ("bakiye",),
    "debit": ("borc",),
    "credit": ("alacak",),
}

_IBAN_RE = re.compile(r"TR\d{2}\s?(?:\d{4}\s?){5}\d{2}")
_PERIOD_RE = re.compile(r"(\d{1,2}\.\d{1,2}\.\d{4})\s*-\s*(\d{1,2}\.\d{1,2}\.\d{4})")


def find_header(rows: Rows, max_scan: int = 40) -> tuple[int, dict[str, int]] | None:
    for i, row in enumerate(rows[:max_scan]):
        cols: dict[str, int] = {}
        for j, v in enumerate(row):
            t = _fold(_cell_text(v))
            if not t:
                continue
            for key, syns in COLUMN_SYNONYMS.items():
                if key not in cols and t in syns:
                    cols[key] = j
        if "date" in cols and "description" in cols and ("amount" in cols or "credit" in cols):
            return i, cols
    return None


def extract_header_meta(rows: Rows, upto: int, st: ParsedStatement) -> None:
    for row in rows[:upto]:
        texts = [_cell_text(v) for v in row if _cell_text(v)]
        if not texts:
            continue
        joined = " ".join(texts)
        if st.iban is None:
            m = _IBAN_RE.search(joined.replace(" ", ""))
            if m:
                st.iban = m.group(0).replace(" ", "")
        if st.period_start is None:
            m = _PERIOD_RE.search(joined)
            if m:
                st.period_start = parse_tr_date(m.group(1))
                st.period_end = parse_tr_date(m.group(2))
        label = _fold(texts[0])
        if label.startswith("hesap numarasi") and len(texts) > 1:
            st.account_no = texts[1]
        if texts[0].startswith("Sayın "):
            st.account_holder = texts[0][len("Sayın ") :].strip()


def parse_table(rows: Rows, header_idx: int, cols: dict[str, int], st: ParsedStatement) -> None:
    for i in range(header_idx + 1, len(rows)):
        row = rows[i]

        def get(key: str) -> Any:
            j = cols.get(key)
            return row[j] if j is not None and j < len(row) else None

        if any(_fold(_cell_text(v)).startswith(("borc:", "alacak:")) for v in row):
            _parse_footer(row, st)
            break
        d = parse_tr_date(get("date"))
        if d is None:
            continue
        if "amount" in cols:
            amount = parse_tr_number(get("amount"))
        else:
            credit = parse_tr_number(get("credit")) or Decimal(0)
            debit = parse_tr_number(get("debit")) or Decimal(0)
            amount = credit - debit
        if amount is None:
            st.warnings.append(f"Satır {i + 1}: tutar okunamadı")
            continue
        st.transactions.append(
            ParsedTransaction(
                txn_date=d,
                receipt_no=_cell_text(get("receipt")) or None,
                description=_cell_text(get("description")),
                amount=amount,
                balance_after=parse_tr_number(get("balance")),
                row_index=i,
            )
        )


def _parse_footer(row: list[Any], st: ParsedStatement) -> None:
    for v in row:
        t = _cell_text(v)
        f = _fold(t)
        if f.startswith("borc:"):
            st.footer_debit_total = parse_tr_number(t.split(":", 1)[1])
        elif f.startswith("alacak:"):
            st.footer_credit_total = parse_tr_number(t.split(":", 1)[1])


def assign_sequences(st: ParsedStatement, newest_first: bool) -> None:
    """Aynı gün içindeki kronolojik sırayı belirler (dedup yedek anahtarı ve bakiye zinciri için)."""
    ordered = list(reversed(st.transactions)) if newest_first else list(st.transactions)
    counters: dict[date, int] = {}
    for t in ordered:
        counters[t.txn_date] = counters.get(t.txn_date, 0) + 1
        t.seq = counters[t.txn_date]


class BankParser:
    code: str = ""
    name: str = ""
    newest_first: bool = True

    def detect(self, rows: Rows) -> bool:
        raise NotImplementedError

    def parse(self, rows: Rows) -> ParsedStatement:
        found = find_header(rows)
        if not found:
            raise StatementParseError("Ekstrede Tarih/Açıklama/Tutar başlık satırı bulunamadı")
        header_idx, cols = found
        st = ParsedStatement(bank_code=self.code, bank_name=self.name)
        extract_header_meta(rows, header_idx, st)
        parse_table(rows, header_idx, cols, st)
        if st.transactions and len(st.transactions) > 1:
            # Tarihe göre azalan mı artan mı? Dosyanın kendisine bak.
            newest_first = st.transactions[0].txn_date >= st.transactions[-1].txn_date
        else:
            newest_first = self.newest_first
        assign_sequences(st, newest_first)
        self._validate(st)
        return st

    def _validate(self, st: ParsedStatement) -> None:
        if st.footer_credit_total is not None:
            credits = sum((t.amount for t in st.transactions if t.amount > 0), Decimal(0))
            if abs(credits - st.footer_credit_total) >= 1:
                st.warnings.append(
                    f"Gelen toplamı ({credits}) ekstre özetindeki Alacak toplamıyla ({st.footer_credit_total}) uyuşmuyor"
                )
        if st.footer_debit_total is not None:
            debits = -sum((t.amount for t in st.transactions if t.amount < 0), Decimal(0))
            if abs(debits - st.footer_debit_total) >= 1:
                st.warnings.append(
                    f"Giden toplamı ({debits}) ekstre özetindeki Borç toplamıyla ({st.footer_debit_total}) uyuşmuyor"
                )


class GenericParser(BankParser):
    """Bilinmeyen bankalar için: başlık satırını bulup tabloyu okur."""

    code = "generic"
    name = "Genel"

    def detect(self, rows: Rows) -> bool:
        return find_header(rows) is not None


_REGISTRY: list[BankParser] = []


def register(parser: BankParser) -> BankParser:
    _REGISTRY.append(parser)
    return parser


def parse_statement(data: bytes) -> ParsedStatement:
    workbook = read_workbook(data)
    for rows in workbook.values():
        for parser in [*_REGISTRY, GenericParser()]:
            if parser.detect(rows):
                return parser.parse(rows)
    raise StatementParseError("Dosya tanınan bir banka ekstresi biçiminde değil")
