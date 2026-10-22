# -*- coding: utf-8 -*-
"""Parse South African bank statement exports (FNB CSV and generic CSV)."""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any

from odoo import _
from odoo.exceptions import UserError


def _parse_fnb_date(value: str):
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y%m%d", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(value: str):
    raw = (value or "").strip().replace(" ", "").replace(",", "")
    if not raw:
        return 0.0
    negative = raw.startswith("-") or raw.endswith("-")
    raw = raw.strip("-")
    try:
        amount = float(raw)
    except ValueError:
        return None
    return -amount if negative else amount


def _normalize_header(cell: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (cell or "").strip().lower()).strip("_")


class AveaBankStatementParser:
    """Stateless parser for bank CSV/OFX uploads."""

    @classmethod
    def parse(cls, filename: str, raw_bytes: bytes) -> dict[str, Any]:
        name = (filename or "").lower()
        text = raw_bytes.decode("utf-8-sig", errors="replace")
        if name.endswith(".ofx") or text.lstrip().startswith("OFXHEADER"):
            return cls._parse_ofx(text)
        return cls._parse_csv(text, filename=name)

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
