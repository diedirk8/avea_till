# -*- coding: utf-8 -*-
"""Parse Yoco payout CSVs and Capitec merchant statements."""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any

from odoo import _
from odoo.exceptions import UserError

_YOCO_HEADERS = {
    "date",
    "amount",
    "fee_amount",
    "fee_vat_amount",
    "capital_repayment",
}
_CAPITEC_PAYOUT_RE = re.compile(
    r"(\d{2}/\d{2}/\d{4})\s+(CAPITEC\s+\d{4}PosSettle\s+(\d{6}))\s+R?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)
_CAPITEC_DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
_CAPITEC_ISO_DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
_CAPITEC_REF_RE = re.compile(r"(CAPITEC\s+\d{4}PosSettle\s+(\d{6}))", re.IGNORECASE)
_CAPITEC_AMOUNT_RE = re.compile(r"R([\d\s]+\.\d{2})")
_CAPITEC_PLAIN_AMOUNT_RE = re.compile(r"\d[\d ]*\.\d{2}")


def _normalize_header(cell: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (cell or "").strip().lower()).strip("_")


def _parse_zar(value: str):
    raw = (value or "").strip().replace(" ", "").replace(",", "")
    if not raw:
        return None
    raw = re.sub(r"(?i)^r", "", raw)
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_date(value: str):
    raw = (value or "").strip()
    if not raw:
        return None
    raw = raw.replace("T", " ").split(" ")[0]
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _date_from_yymmdd(value: str):
    try:
        return datetime.strptime(value, "%y%m%d").date()
    except ValueError:
        return None


def _csv_body(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].lower().startswith("sep="):
        return "\n".join(lines[1:])
    return text


class AveaMerchantPayoutParser:
    """Stateless parser for card-machine payout files."""

    @classmethod
    def detect(cls, filename: str, raw_bytes: bytes) -> str | None:
        name = (filename or "").lower()
        if name.endswith(".pdf") or (raw_bytes[:5] == b"%PDF-"):
            text = cls._pdf_text(raw_bytes)
            lowered = text.lower()
            if "merchant statement" in lowered and "capitec" in lowered:
                return "capitec"
            if "first national bank" in lowered or "gold business account" in lowered:
                return "fnb"
            return None
        text = raw_bytes.decode("utf-8-sig", errors="replace")
        headers = cls._yoco_headers(text)
        if _YOCO_HEADERS <= headers:
            return "yoco"
        lowered = (name + " " + text[:400]).lower()
        if "yoco" in lowered and "capital repayment" in lowered:
            return "yoco"
        return None

    @classmethod
    def parse(cls, filename: str, raw_bytes: bytes) -> dict[str, Any]:
        kind = cls.detect(filename, raw_bytes)
        if kind == "yoco":
            return cls._parse_yoco_csv(raw_bytes.decode("utf-8-sig", errors="replace"))
        if kind == "capitec":
            return cls._parse_capitec_pdf(raw_bytes)
        if kind == "fnb":
            raise UserError(
                _(
                    "This is the FNB bank statement. Attach it as the bank statement, "
                    "not as a card-machine file."
                )
            )
        raise UserError(
            _(
                "Could not read this card-machine file. Use a Yoco payouts CSV "
                "(Date, Amount, Fee, Capital Repayment) or a Capitec merchant statement PDF."
            )
        )

    @classmethod
    def _yoco_headers(cls, text: str) -> set[str]:
        body = _csv_body(text)
        reader = csv.reader(io.StringIO(body))
        try:
            row = next(reader)
        except StopIteration:
            return set()
        return {_normalize_header(cell) for cell in row}

    @classmethod
    def _parse_yoco_csv(cls, text: str) -> dict[str, Any]:
        body = _csv_body(text)
        reader = csv.DictReader(io.StringIO(body))
        if not reader.fieldnames:
            raise UserError(_("The Yoco CSV has no header row."))
        col = {_normalize_header(name): name for name in reader.fieldnames if name}
        if "date" not in col or "amount" not in col:
            raise UserError(_("The Yoco CSV needs Date and Amount columns."))
        payouts = []
        for row in reader:
            if not any((cell or "").strip() for cell in row.values()):
                continue
            payout_date = _parse_date(row.get(col["date"]) or "")
            net = _parse_zar(row.get(col["amount"]) or "")
            if not payout_date or net is None:
                continue
            fee = _parse_zar(row.get(col.get("fee_amount", ""), "0")) or 0.0
            vat = _parse_zar(row.get(col.get("fee_vat_amount", ""), "0")) or 0.0
            capital = _parse_zar(row.get(col.get("capital_repayment", ""), "0")) or 0.0
            state = (row.get(col.get("state", ""), "") or "").strip().lower()
            fee_total = round(fee + vat, 2)
            gross = round(net + fee_total + capital, 2)
            payouts.append(
                {
                    "provider": "yoco",
                    "payout_date": payout_date,
                    "trading_date": False,
                    "net_amount": net,
                    "gross_amount": gross,
                    "fee_amount": fee_total,
                    "capital_amount": capital,
                    "reference": "",
                    "state": state or "paid",
                }
            )
        if not payouts:
            raise UserError(_("No payouts were found in the Yoco CSV."))
        dates = [row["payout_date"] for row in payouts]
        return {
            "provider": "yoco",
            "source": "yoco_csv",
            "date_from": min(dates),
            "date_to": max(dates),
            "payouts": payouts,
        }

    @classmethod
    def _pdf_text(cls, raw_bytes: bytes) -> str:
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
                        "PDF merchant statements need pdfminer or PyPDF2 on the server. "
                        "Ask your administrator to install pdfminer.six."
                    )
                )
            reader = PyPDF2.PdfReader(buffer)
            return "\n".join((page.extract_text() or "") for page in reader.pages)

    @classmethod
    def _parse_capitec_pdf(cls, raw_bytes: bytes) -> dict[str, Any]:
        text = cls._pdf_text(raw_bytes)
        return cls._parse_capitec_text(text)

    @classmethod
    def _parse_capitec_text(cls, text: str) -> dict[str, Any]:
        cleaned = re.sub(r"\r\n?", "\n", text or "")
        if "merchant statement" not in cleaned.lower() or "capitec" not in cleaned.lower():
            raise UserError(_("This PDF is not a Capitec merchant statement."))
        net_rows = cls._capitec_block(cleaned, r"All settlements")
        gross_rows = cls._capitec_block(cleaned, r"Settlements for card machine")
        if not net_rows:
            net_rows, gross_rows = cls._capitec_legacy_deposits(cleaned)
        if not net_rows:
            raise UserError(_("No Capitec payouts were found on this merchant statement."))
        gross_by_key = {cls._capitec_key(row): row for row in gross_rows}
        payouts = []
        for row in net_rows:
            gross_row = gross_by_key.get(cls._capitec_key(row))
            net = row["amount"]
            gross = gross_row["amount"] if gross_row else net
            fee = round(gross - net, 2)
            payouts.append(
                {
                    "provider": "capitec",
                    "payout_date": row["payout_date"],
                    "trading_date": row["trading_date"],
                    "net_amount": net,
                    "gross_amount": gross,
                    "fee_amount": fee if fee > 0 else 0.0,
                    "capital_amount": 0.0,
                    "reference": row["reference"],
                    "state": "paid",
                }
            )
        dates = [row["payout_date"] for row in payouts]
        return {
            "provider": "capitec",
            "source": "capitec_pdf",
            "date_from": min(dates),
            "date_to": max(dates),
            "payouts": payouts,
        }

    @classmethod
    def _capitec_key(cls, row: dict[str, Any]) -> tuple:
        return (row["payout_date"], row["reference"])

    @classmethod
    def _capitec_block(cls, text: str, heading: str) -> list[dict[str, Any]]:
        match = re.search(heading, text, flags=re.IGNORECASE)
        if not match:
            return []
        chunk = text[match.end() :]
        next_heading = re.search(
            r"(?:Settlements for card machine|Overview|Notices)\b",
            chunk,
            flags=re.IGNORECASE,
        )
        if next_heading and next_heading.start() > 20:
            chunk = chunk[: next_heading.start()]
        rows = cls._capitec_inline_rows(chunk)
        if rows:
            return rows
        return cls._capitec_column_rows(chunk)

    @classmethod
    def _capitec_legacy_deposits(cls, text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Older Capitec PDFs print DETAIL OF DEPOSITS as separate date/ref/amount columns."""
        if "detail of deposits" not in (text or "").lower():
            return [], []
        batch = re.search(
            r"Batch Transmission Date\s*((?:20\d{2}-\d{2}-\d{2}\s*)+)",
            text,
            flags=re.IGNORECASE,
        )
        if not batch:
            return [], []
        dates = [_parse_date(value) for value in _CAPITEC_ISO_DATE_RE.findall(batch.group(1))]
        dates = [value for value in dates if value]
        ref_block = re.search(
            r"Reference Number\s*((?:CAPITEC\s+\d{4}PosSettle\s+\d{6}\s*)+)",
            text,
            flags=re.IGNORECASE,
        )
        refs = [
            (re.sub(r"\s+", " ", found.group(1)).strip(), found.group(2))
            for found in _CAPITEC_REF_RE.finditer(ref_block.group(1) if ref_block else "")
        ]
        net_headers = list(re.finditer(r"Total Deposit Amount", text, flags=re.IGNORECASE))
        if not net_headers:
            return [], []
        rest = text[net_headers[-1].end() :]
        stop = re.search(r"A registered credit provider|Terminal ID", rest, flags=re.IGNORECASE)
        nets = [_parse_zar(value) for value in _CAPITEC_PLAIN_AMOUNT_RE.findall(rest[: stop.start()] if stop else rest)]
        nets = [value for value in nets if value is not None]
        if len(nets) >= 2 and abs(nets[-1] - round(sum(nets[:-1]), 2)) < 0.05:
            nets = nets[:-1]
        gross: list = []
        gross_headers = list(re.finditer(r"Batch Total", text, flags=re.IGNORECASE))
        if gross_headers:
            rest = text[gross_headers[-1].end() :]
            stop = re.search(r"A registered credit provider|Page \d+", rest, flags=re.IGNORECASE)
            gross = [
                _parse_zar(value)
                for value in _CAPITEC_PLAIN_AMOUNT_RE.findall(rest[: stop.start()] if stop else rest)
            ]
            gross = [value for value in gross if value is not None]
        count = min(len(dates), len(refs), len(nets))
        if count < 1:
            return [], []
        net_rows = []
        for index in range(count):
            reference, trading = refs[index]
            net_rows.append(
                {
                    "payout_date": dates[index],
                    "reference": reference,
                    "amount": nets[index],
                    "trading_date": _date_from_yymmdd(trading),
                }
            )
        gross_rows = []
        if len(gross) == count:
            for index in range(count):
                reference, trading = refs[index]
                gross_rows.append(
                    {
                        "payout_date": dates[index],
                        "reference": reference,
                        "amount": gross[index],
                        "trading_date": _date_from_yymmdd(trading),
                    }
                )
        return net_rows, gross_rows

    @classmethod
    def _capitec_inline_rows(cls, chunk: str) -> list[dict[str, Any]]:
        rows = []
        seen = set()
        for found in _CAPITEC_PAYOUT_RE.finditer(re.sub(r"\s+", " ", chunk)):
            payout_date = _parse_date(found.group(1))
            amount = _parse_zar(found.group(4))
            if not payout_date or amount is None:
                continue
            reference = re.sub(r"\s+", " ", found.group(2)).strip()
            key = (payout_date, reference, amount)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "payout_date": payout_date,
                    "reference": reference,
                    "amount": amount,
                    "trading_date": _date_from_yymmdd(found.group(3)),
                }
            )
        return rows

    @classmethod
    def _capitec_column_rows(cls, chunk: str) -> list[dict[str, Any]]:
        """Capitec merchant PDFs print date, reference, and amount as separate columns."""
        first_date = _CAPITEC_DATE_RE.search(chunk)
        body = chunk[first_date.start() :] if first_date else chunk
        dates = [_parse_date(value) for value in _CAPITEC_DATE_RE.findall(body)]
        dates = [value for value in dates if value]
        refs = [
            (re.sub(r"\s+", " ", found.group(1)).strip(), found.group(2))
            for found in _CAPITEC_REF_RE.finditer(body)
        ]
        amounts = [_parse_zar(value) for value in _CAPITEC_AMOUNT_RE.findall(body)]
        amounts = [value for value in amounts if value is not None]
        count = min(len(dates), len(refs), len(amounts))
        if count < 1:
            return []
        rows = []
        for index in range(count):
            reference, trading = refs[index]
            rows.append(
                {
                    "payout_date": dates[index],
                    "reference": reference,
                    "amount": amounts[index],
                    "trading_date": _date_from_yymmdd(trading),
                }
            )
        return rows
