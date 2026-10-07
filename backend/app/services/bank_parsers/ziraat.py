from __future__ import annotations

from app.services.bank_parsers.base import BankParser, _cell_text, find_header, register
from app.services.xlsx.reader import Rows


class ZiraatParser(BankParser):
    code = "ziraat"
    name = "Ziraat Bankası"
    newest_first = True

    def detect(self, rows: Rows) -> bool:
        has_marker = False
        for row in rows:
            for v in row:
                t = _cell_text(v).lower()
                if "ziraatbank" in t or "ziraat bankası" in t:
                    has_marker = True
                    break
            if has_marker:
                break
        if not has_marker:
            # Ziraat IBAN banka kodu: 00010
            for row in rows[:20]:
                for v in row:
                    t = _cell_text(v).replace(" ", "")
                    if t.startswith("TR") and len(t) == 26 and t[4:9] == "00010":
                        has_marker = True
        return has_marker and find_header(rows) is not None


register(ZiraatParser())
