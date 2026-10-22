# -*- coding: utf-8 -*-
"""Parse South African bank statement exports (FNB PDF/CSV and generic CSV/OFX)."""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Any

from odoo import _
from odoo.exceptions import UserError

_MONTH_ABBR = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_AMOUNT_RE = r"-?(?:\d{1,3}(?:[,\s]\d{3})*|\d+)\.\d{2}"
_FNB_PDF_LINE_RE = re.compile(
    rf"^(\d{{1,2}}\s+[A-Za-z]{{3}}|\d{{4}}-\d{{2}}-\d{{2}})\s+"
    rf"(.+?)\s+({_AMOUNT_RE})\s+({_AMOUNT_RE})(?:\s+({_AMOUNT_RE}))?\s*$"
)
_FNB_TX_DATE_RE = re.compile(
    r"^(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))"
    r"(?:\s+(.*))?$",
    re.IGNORECASE,
)
_FNB_PDF_AMOUNT_LINE_RE = re.compile(r"^-?[\d,]+\.\d{2}(?:Cr|Dr)?\s*$", re.IGNORECASE)
_FNB_REF_LINE_RE = re.compile(
    r"^(Pets Empire|Petshop|Pets79|Petsempire|Pem402|\d{6}\*)",
    re.IGNORECASE,
)
_FNB_TRANSACTIONS_SECTION_RE = re.compile(
    r"Transactions in RAND \(ZAR\)\s*:?\s*\d*",
    re.IGNORECASE,
)


def _parse_fnb_date(value: str):
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y%m%d", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    short = re.match(r"(\d{1,2})\s+([A-Za-z]{3,9})", raw)
    if short:
        month = _MONTH_ABBR.get(short.group(2).lower()[:3])
        if month:
            try:
                return date(datetime.today().year, month, int(short.group(1)))
            except ValueError:
                return None
    return None


def _parse_long_date(value: str):
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _infer_tx_year(month: int, period_start: date | None, period_end: date | None) -> int:
    if period_end:
        year = period_end.year
        if period_start and period_start.year < year:
            if month < period_start.month:
                return year
            if month > period_end.month:
                return period_start.year
        return year
    return datetime.today().year


def _parse_dd_mon(value: str, period_start: date | None, period_end: date | None):
    raw = (value or "").strip()
    parsed = _parse_fnb_date(raw)
    if parsed and re.match(r"\d{4}-\d{2}-\d{2}", raw):
        return parsed
    match = re.match(r"(\d{1,2})\s+([A-Za-z]{3})", raw)
    if not match:
        return None
    month = _MONTH_ABBR.get(match.group(2).lower())
    if not month:
        return None
    year = _infer_tx_year(month, period_start, period_end)
    try:
        return date(year, month, int(match.group(1)))
    except ValueError:
        return None


def _parse_amount(value: str):
    raw = (value or "").strip().replace(",", "").replace(" ", "")
    if not raw:
        return 0.0
    negative = raw.startswith("-") or raw.endswith("-")
    raw = raw.strip("-")
    try:
        amount = float(raw)
    except ValueError:
        return None
    return -amount if negative else amount


def _normalize_pdf_token(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip())


def _parse_fnb_pdf_amount(value: str):
    """Parse FNB PDF amount tokens (optional Cr/Dr suffix, thousands separators)."""
    raw = _normalize_pdf_token(value)
    if not raw:
        return None
    is_credit = raw.lower().endswith("cr")
    is_debit = raw.lower().endswith("dr")
    raw = re.sub(r"(?i)(cr|dr)$", "", raw)
    negative = raw.startswith("-")
    raw = raw.lstrip("-")
    try:
        amount = float(raw.replace(",", ""))
    except ValueError:
        return None
    if is_credit:
        return amount
    if is_debit:
        return -amount
    if negative:
        return -amount
    return -abs(amount)


def _normalize_header(cell: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (cell or "").strip().lower()).strip("_")


class AveaBankStatementParser:
    """Stateless parser for bank CSV/OFX/PDF uploads."""

    @classmethod
    def parse(cls, filename: str, raw_bytes: bytes) -> dict[str, Any]:
        name = (filename or "").lower()
        if name.endswith(".pdf") or raw_bytes[:5] == b"%PDF-":
            return cls._parse_pdf(raw_bytes)
        text = raw_bytes.decode("utf-8-sig", errors="replace")
        if name.endswith(".ofx") or text.lstrip().startswith("OFXHEADER"):
            return cls._parse_ofx(text)
        return cls._parse_csv(text, filename=name)

    @classmethod
    def _pdf_extract_text(cls, raw_bytes: bytes) -> str:
        buffer = io.BytesIO(raw_bytes)
        try:
            from pdfminer.high_level import extract_text

            return extract_text(buffer) or ""
        except ImportError:
            buffer.seek(0)
            try:
                import PyPDF2
            except ImportError:
                raise UserError(
                    _(
                        "PDF statements need pdfminer or PyPDF2 on the server. "
                        "Ask your administrator to install pdfminer.six."
                    )
                )
            reader = PyPDF2.PdfReader(buffer)
            if reader.is_encrypted:
                raise UserError(
                    _("This PDF is password-protected. Download it without a password or use CSV/OFX.")
                )
            return "\n".join((page.extract_text() or "") for page in reader.pages)

    @classmethod
    def _parse_pdf(cls, raw_bytes: bytes) -> dict[str, Any]:
        text = cls._pdf_extract_text(raw_bytes)
        cleaned = re.sub(r"\r\n?", "\n", text)
        if len(cleaned.strip()) < 40:
            raise UserError(
                _(
                    "This PDF has no readable text (it may be a scan). "
                    "Download the digital statement from FNB Online Banking, or export CSV/OFX "
                    "if your profile has those formats under Statements or Scheduled Exports."
                )
            )
        if cls._looks_like_fnb_pdf(cleaned):
            return cls._parse_fnb_pdf_text(cleaned)
        parsed = cls._parse_fnb_pdf_text(cleaned)
        if parsed.get("transactions"):
            return parsed
        raise UserError(
            _(
                "Could not read transactions from this PDF. Use an FNB statement PDF "
                "with Date, Description, Amount, and Balance columns, or try CSV/OFX."
            )
        )

    @classmethod
    def _looks_like_fnb_pdf(cls, text: str) -> bool:
        lowered = text.lower()
        return "first national bank" in lowered or "fnb" in lowered or "recreated statement" in lowered

    @classmethod
    def _extract_fnb_statement_period(cls, text: str) -> tuple[date | None, date | None]:
        patterns = [
            r"Statement\s+Period\s*:\s*(\d{1,2}\s+\w+\s+\d{4})\s+to\s+(\d{1,2}\s+\w+\s+\d{4})",
            r"statement\s+period[:\s]*\s*(\d{1,2}\s+\w+\s+\d{4})\s*(?:to|–|-)\s*(\d{1,2}\s+\w+\s+\d{4})",
            r"from\s+(\d{1,2}\s+\w+\s+\d{4})\s+to\s+(\d{1,2}\s+\w+\s+\d{4})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                start = _parse_long_date(match.group(1))
                end = _parse_long_date(match.group(2))
                return start, end
        return None, None

    @classmethod
    def _parse_fnb_pdf_meta(cls, text: str, period_end: date | None) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        account = re.search(
            r"(?:Gold Business Account|account\s+(?:number|no\.?))\s*:?\s*([*\d]{8,15})",
            text,
            flags=re.IGNORECASE,
        )
        if account:
            meta["account_number"] = re.sub(r"[^\d]", "", account.group(1)) or account.group(1).strip()
        opening = re.search(
            r"Opening\s+Balance\s+([\d,]+\.\d{2}(?:Cr|Dr)?)",
            text,
            flags=re.IGNORECASE,
        )
        closing = re.search(
            r"Closing\s+Balance\s+([\d,]+\.\d{2}(?:Cr|Dr)?)",
            text,
            flags=re.IGNORECASE,
        )
        if opening:
            meta["opening_balance"] = _parse_fnb_pdf_amount(opening.group(1))
        if closing:
            meta["closing_balance"] = _parse_fnb_pdf_amount(closing.group(1))
        if period_end:
            meta["statement_date"] = period_end
        return meta

    @classmethod
    def _parse_fnb_pdf_single_line_rows(
        cls,
        text: str,
        period_start: date | None,
        period_end: date | None,
    ) -> list[dict[str, Any]]:
        skip_fragments = (
            "date description",
            "accrued bank",
            "opening balance",
            "closing balance",
            "statement period",
            "page ",
            "continued",
            "first national bank",
            "total debits",
            "total credits",
            "transactions in rand",
        )
        transactions: list[dict[str, Any]] = []
        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", (raw_line or "").strip())
            if not line or len(line) < 12:
                continue
            lowered = line.lower()
            if any(fragment in lowered for fragment in skip_fragments):
                continue
            match = _FNB_PDF_LINE_RE.match(line)
            if not match:
                continue
            tx_date = _parse_dd_mon(match.group(1), period_start, period_end)
            if not tx_date:
                continue
            amount = _parse_fnb_pdf_amount(match.group(3))
            balance = _parse_fnb_pdf_amount(match.group(4))
            if amount is None:
                continue
            transactions.append(
                {
                    "date": tx_date,
                    "description": match.group(2).strip(),
                    "reference": "",
                    "amount": amount,
                    "balance": balance,
                }
            )
        return transactions

    @classmethod
    def _parse_fnb_gold_business_pdf(cls, text: str, period_start: date | None, period_end: date | None):
        """FNB Gold Business PDFs export table columns separately (not one row per line)."""
        if not _FNB_TRANSACTIONS_SECTION_RE.search(text):
            return []
        default_year = period_end.year if period_end else datetime.today().year
        transactions: list[dict[str, Any]] = []
        for part in _FNB_TRANSACTIONS_SECTION_RE.split(text)[1:]:
            part = re.split(r"\nPage \d+ of", part, maxsplit=1)[0]
            lines = [line.strip() for line in part.splitlines() if line.strip()]
            filtered = [
                line
                for line in lines
                if line.lower() not in ("date", "description", "amount", "balance")
                and not line.lower().startswith("accrued")
            ]
            descriptions: list[tuple[str, str]] = []
            amount_tokens: list[str] = []
            mode = "desc"
            seen_description = False
            index = 0
            while index < len(filtered):
                line = filtered[index]
                if mode == "desc":
                    match = _FNB_TX_DATE_RE.match(line)
                    if match:
                        date_label = match.group(1)
                        description = (match.group(2) or "").strip()
                        if not description:
                            index += 1
                            if index >= len(filtered):
                                break
                            description = filtered[index].strip()
                        if _FNB_REF_LINE_RE.match(description):
                            index += 1
                            continue
                        descriptions.append((date_label, description))
                        seen_description = True
                        index += 1
                        continue
                    if seen_description and _FNB_PDF_AMOUNT_LINE_RE.match(_normalize_pdf_token(line)):
                        mode = "amt"
                        amount_tokens.append(line)
                        index += 1
                        continue
                    index += 1
                    continue
                if _FNB_PDF_AMOUNT_LINE_RE.match(_normalize_pdf_token(line)):
                    amount_tokens.append(line)
                    index += 1
                    continue
                if _FNB_TX_DATE_RE.match(line):
                    mode = "desc"
                    continue
                if line.startswith("Closing") or line.startswith("Turnover"):
                    break
                index += 1
            row_count = len(descriptions)
            if not row_count or len(amount_tokens) < row_count:
                continue
            amount_lines = amount_tokens[:row_count]
            balance_lines = (
                amount_tokens[row_count : row_count * 2]
                if len(amount_tokens) >= row_count * 2
                else [None] * row_count
            )
            for row_index, (date_label, description) in enumerate(descriptions):
                tx_date = _parse_dd_mon(date_label, period_start, period_end) or _parse_fnb_date(
                    f"{date_label} {default_year}"
                )
                if not tx_date:
                    continue
                amount = _parse_fnb_pdf_amount(amount_lines[row_index])
                if amount is None:
                    continue
                balance = (
                    _parse_fnb_pdf_amount(balance_lines[row_index])
                    if balance_lines[row_index]
                    else None
                )
                transactions.append(
                    {
                        "date": tx_date,
                        "description": description,
                        "reference": "",
                        "amount": amount,
                        "balance": balance,
                    }
                )
        return transactions

    @classmethod
    def _parse_fnb_pdf_text(cls, text: str) -> dict[str, Any]:
        period_start, period_end = cls._extract_fnb_statement_period(text)
        meta = cls._parse_fnb_pdf_meta(text, period_end)
        transactions = cls._parse_fnb_gold_business_pdf(text, period_start, period_end)
        if not transactions:
            transactions = cls._parse_fnb_pdf_single_line_rows(text, period_start, period_end)
        return cls._result(meta, transactions, "fnb_pdf")

    @classmethod
    def _parse_csv(cls, text: str, filename: str = "") -> dict[str, Any]:
        if "fnb" in filename or cls._looks_like_fnb_kv(text):
            parsed = cls._parse_fnb_kv_csv(text)
            if parsed["transactions"]:
                return parsed
        header_row = cls._find_transaction_header_row(text)
        if header_row is not None:
            return cls._parse_headered_csv(text, header_row)
        raise UserError(
            _(
                "Could not read this CSV. Export from FNB Online Banking as "
                "“CSV” or use a file with columns for date, description, and amount."
            )
        )

    @classmethod
    def _looks_like_fnb_kv(cls, text: str) -> bool:
        lowered = text.lower()
        return "recreated statement" in lowered or "effective date" in lowered

    @classmethod
    def _parse_fnb_kv_csv(cls, text: str) -> dict[str, Any]:
        """FNB ‘CSV Statement’ key/value header + transaction rows."""
        reader = csv.reader(io.StringIO(text))
        rows = [row for row in reader if row and any(cell.strip() for cell in row)]
        meta: dict[str, Any] = {}
        transactions: list[dict[str, Any]] = []
        header_map = None
        for row in rows:
            label = (row[0] or "").strip().lower()
            if label in ("effective date", "date") and len(row) > 1 and not _parse_fnb_date(row[1]):
                header_map = {_normalize_header(cell): idx for idx, cell in enumerate(row)}
                continue
            if header_map:
                tx = cls._row_from_header_map(row, header_map)
                if tx:
                    transactions.append(tx)
                continue
            if _parse_fnb_date(row[0]):
                tx_date = _parse_fnb_date(row[0])
                description = row[1].strip() if len(row) > 1 else ""
                reference = row[2].strip() if len(row) > 2 else ""
                amount = _parse_amount(row[-2] if len(row) >= 5 else row[-1])
                balance = _parse_amount(row[-1]) if len(row) >= 6 else None
                if amount is None:
                    continue
                transactions.append(
                    {
                        "date": tx_date,
                        "description": description,
                        "reference": reference,
                        "amount": amount,
                        "balance": balance,
                    }
                )
                continue
            cls._store_fnb_meta(meta, row)
        return cls._result(meta, transactions, "fnb_csv")

    @classmethod
    def _row_from_header_map(cls, row: list[str], header_map: dict[str, int]) -> dict | None:
        def cell(name, *aliases):
            for key in (name,) + aliases:
                idx = header_map.get(key)
                if idx is not None and idx < len(row):
                    return row[idx].strip()
            return ""

        tx_date = _parse_fnb_date(cell("effective_date", "date", "transaction_date"))
        amount = _parse_amount(cell("amount", "transaction_amount"))
        if not tx_date or amount is None:
            return None
        return {
            "date": tx_date,
            "description": cell("description", "narrative"),
            "reference": cell("reference", "cheque_ref"),
            "amount": amount,
            "balance": _parse_amount(cell("balance")),
        }

    @classmethod
    def _store_fnb_meta(cls, meta: dict, row: list[str]):
        if not row:
            return
        key = (row[0] or "").strip().lower()
        val = row[1].strip() if len(row) > 1 else ""
        if key == "date" and not meta.get("statement_date"):
            meta["statement_date"] = _parse_fnb_date(val)
        elif key == "account number":
            meta["account_number"] = val
        elif key == "opening balance":
            meta["opening_balance"] = _parse_amount(val)
        elif key == "closing balance":
            meta["closing_balance"] = _parse_amount(val)

    @classmethod
    def _find_transaction_header_row(cls, text: str) -> int | None:
        reader = csv.reader(io.StringIO(text))
        for index, row in enumerate(reader):
            headers = {_normalize_header(cell) for cell in row}
            if {"amount", "date"} <= headers or {"transaction_amount", "transaction_date"} <= headers:
                return index
            if "effective_date" in headers and "amount" in headers:
                return index
            if "narrative" in headers and "transaction_amount" in headers:
                return index
        return None

    @classmethod
    def _parse_headered_csv(cls, text: str, header_index: int) -> dict[str, Any]:
        lines = text.splitlines()
        reader = csv.reader(io.StringIO("\n".join(lines[header_index:])))
        rows = list(reader)
        if not rows:
            raise UserError(_("The CSV file has no transaction rows."))
        header = [_normalize_header(cell) for cell in rows[0]]
        col = {name: idx for idx, name in enumerate(header)}
        date_keys = ("effective_date", "date", "transaction_date", "value_date")
        desc_keys = ("description", "narrative", "memo", "details")
        ref_keys = ("reference", "cheque_ref", "cheque_ref_number", "ref")
        amount_keys = ("amount", "transaction_amount")
        balance_keys = ("balance", "running_balance")

        def pick(keys):
            for key in keys:
                if key in col:
                    return col[key]
            return None

        date_col = pick(date_keys)
        desc_col = pick(desc_keys)
        ref_col = pick(ref_keys)
        amount_col = pick(amount_keys)
        balance_col = pick(balance_keys)
        if date_col is None or amount_col is None:
            raise UserError(_("Could not find date and amount columns in the CSV header."))

        transactions = []
        for row in rows[1:]:
            if not row or not any(cell.strip() for cell in row):
                continue
            tx_date = _parse_fnb_date(row[date_col])
            if not tx_date:
                continue
            amount = _parse_amount(row[amount_col])
            if amount is None:
                continue
            transactions.append(
                {
                    "date": tx_date,
                    "description": row[desc_col].strip() if desc_col is not None and desc_col < len(row) else "",
                    "reference": row[ref_col].strip() if ref_col is not None and ref_col < len(row) else "",
                    "amount": amount,
                    "balance": _parse_amount(row[balance_col])
                    if balance_col is not None and balance_col < len(row)
                    else None,
                }
            )
        return cls._result({}, transactions, "csv")

    @classmethod
    def _parse_ofx(cls, text: str) -> dict[str, Any]:
        transactions = []
        meta: dict[str, Any] = {}
        chunks = re.split(r"<STMTTRN>", text, flags=re.IGNORECASE)
        for chunk in chunks[1:]:
            date_m = re.search(r"<DTPOSTED>(\d{8})", chunk, flags=re.IGNORECASE)
            amount_m = re.search(r"<TRNAMT>([-+0-9.]+)", chunk, flags=re.IGNORECASE)
            name_m = re.search(r"<NAME>([^\n<]+)", chunk, flags=re.IGNORECASE)
            memo_m = re.search(r"<MEMO>([^\n<]+)", chunk, flags=re.IGNORECASE)
            fitid_m = re.search(r"<FITID>([^\n<]+)", chunk, flags=re.IGNORECASE)
            if not date_m or not amount_m:
                continue
            tx_date = _parse_fnb_date(date_m.group(1)[:8])
            if not tx_date:
                continue
            try:
                amount = float(amount_m.group(1))
            except ValueError:
                continue
            description = (name_m.group(1) if name_m else "") or (memo_m.group(1) if memo_m else "")
            transactions.append(
                {
                    "date": tx_date,
                    "description": description.strip(),
                    "reference": (fitid_m.group(1).strip() if fitid_m else ""),
                    "amount": amount,
                    "balance": None,
                }
            )
        acct_m = re.search(r"<ACCTID>([^\n<]+)", text, flags=re.IGNORECASE)
        if acct_m:
            meta["account_number"] = acct_m.group(1).strip()
        if not transactions:
            raise UserError(_("No transactions were found in the OFX file."))
        return cls._result(meta, transactions, "ofx")

    @classmethod
    def _result(cls, meta: dict, transactions: list, source: str) -> dict[str, Any]:
        if not transactions:
            raise UserError(_("No transactions were found in the uploaded statement."))
        dates = [tx["date"] for tx in transactions if tx.get("date")]
        return {
            "source": source,
            "account_number": meta.get("account_number"),
            "statement_date": meta.get("statement_date"),
            "opening_balance": meta.get("opening_balance"),
            "closing_balance": meta.get("closing_balance"),
            "date_from": min(dates) if dates else None,
            "date_to": max(dates) if dates else None,
            "transactions": transactions,
        }
