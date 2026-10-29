# -*- coding: utf-8 -*-
"""Read a supplier invoice (digital PDF, scan, or photo) into receive lines.

Digital PDFs are read as text. Scans and photos stay on this server and are read
with Tesseract. Nothing is sent to an external service.
"""
import base64
import io
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

_MONEY_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[ \u00a0]\d{3})+|\d+)([.,])(\d{2})(?!\d)"
)
_QTY_RE = re.compile(r"(\d+(?:[.,]\d+)?)")
_CODE_RE = re.compile(r"\b([A-Z0-9][A-Z0-9\-]{3,})\b")
_INVOICE_NO_RE = re.compile(
    r"(?:tax\s+invoice|invoice|inv\.?)\s*(?:no\.?|number|num|#)?\s*[:\-]?\s*"
    r"([A-Z0-9][A-Z0-9\-\/]{2,24})",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4}|"
    r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})"
)
_VAT_RATE_RE = re.compile(
    r"vat\s*(?:@|at)?\s*(\d{1,2}(?:[.,]\d+)?)\s*%",
    re.IGNORECASE,
)
_FOOTER_RE = re.compile(
    r"^(sub\s*total|total|grand\s+total|amount\s+due|balance|vat|tax|"
    r"discount|rounding|page\b|tel\b|fax\b|e-?mail|bank\b|account\b|"
    r"invoice\b|tax\s+invoice|delivery\b|customer\b|supplier\b|"
    r"registration|reg\.?\s*no)",
    re.IGNORECASE,
)
_INCLUSIVE_RE = re.compile(
    r"(incl\.?\s*vat|vat\s*incl|inclusive\s+of\s+vat|prices?\s+include\s+vat|"
    r"including\s+vat)",
    re.IGNORECASE,
)
_EXCLUSIVE_RE = re.compile(
    r"(excl\.?\s*vat|vat\s*excl|exclusive\s+of\s+vat|prices?\s+exclude\s+vat|"
    r"excluding\s+vat|ex\s*vat)",
    re.IGNORECASE,
)
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%d-%m-%y",
    "%d %b %Y",
    "%d %B %Y",
    "%B %d, %Y",
    "%b %d, %Y",
)
# A product code on its own line, as pdfminer emits for column-style invoices.
_CODE_LINE_RE = re.compile(r"^[A-Z]{2,}(?:-[A-Z0-9]+){2,}$")
_ISO_DATE_LINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INT_LINE_RE = re.compile(r"^\d{1,5}$")
_MONEY_LINE_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}$")
_LOT_LINE_RE = re.compile(r"^\d+[A-Z]\d[A-Z0-9]*\d$")
_NOT_A_SUPPLIER = re.compile(
    r"^(ship\s+to|customer|page\b|address|description|invoice\b|tax\s+invoice|"
    r"your\s+reference|order\s+no|due\s+date|payment|contact|vat\b|e-?mail|"
    r"phone|banking|no\.?\b|qty\b|unit\s+price)",
    re.IGNORECASE,
)
_MONTH_DATE_RE = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+\d{4})\b",
    re.IGNORECASE,
)
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}


def _to_float(token):
    token = (token or "").strip().replace("\u00a0", "").replace(" ", "")
    if not token:
        return None
    if "," in token and "." in token:
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token:
        token = token.replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


class AveaSupplierInvoiceReader:
    """Turn invoice bytes into header fields and candidate lines."""

    @classmethod
    def read_document(cls, filename, raw_bytes):
        text, source = cls.extract_text(filename, raw_bytes)
        parsed = cls.parse_text(text)
        parsed["source"] = source
        return parsed

    @classmethod
    def extract_text(cls, filename, raw_bytes):
        name = (filename or "").lower()
        suffix = Path(name).suffix
        is_pdf = suffix == ".pdf" or (raw_bytes or b"")[:5] == b"%PDF-"
        if is_pdf:
            text = cls._pdf_text(raw_bytes)
            if len((text or "").strip()) >= 40:
                return text, "pdf"
            return cls._ocr_pdf(raw_bytes), "ocr"
        if suffix in _IMAGE_SUFFIXES:
            return cls._ocr_image(raw_bytes, suffix), "ocr"
        try:
            return raw_bytes.decode("utf-8-sig"), "text"
        except UnicodeDecodeError as error:
            raise ValueError(
                "This file is not a PDF, a photo, or a text invoice."
            ) from error

    @classmethod
    def parse_text(cls, text):
        cleaned = re.sub(r"\r\n?", "\n", text or "")
        vat_mode, vat_rate = cls._vat(cleaned)
        lines = []
        for raw_line in cleaned.split("\n"):
            parsed = cls._parse_line(raw_line)
            if parsed:
                lines.append(parsed)
        # Some invoices (Biofarm and similar) put each column on its own line.
        if not lines:
            lines = cls._parse_column_blocks(cleaned)
        return {
            "invoice_number": cls._invoice_number(cleaned),
            "invoice_date": cls._invoice_date(cleaned),
            "supplier_hint": cls._supplier_hint(cleaned),
            "vat_mode": vat_mode,
            "vat_rate": vat_rate,
            "subtotal": cls._printed_subtotal(cleaned, lines),
            "lines": lines,
            "text": cleaned,
        }

    @classmethod
    def _vat(cls, text):
        rate = 15.0
        match = _VAT_RATE_RE.search(text or "")
        if match:
            parsed = _to_float(match.group(1))
            if parsed and 0 < parsed < 50:
                rate = parsed
        flat = re.sub(r"\s+", " ", text or "")
        # The unit-price column label wins over a grand total that says "Incl VAT".
        if re.search(r"unit\s+price\s+excl", flat, re.IGNORECASE):
            return "exclusive", rate
        if re.search(r"unit\s+price\s+incl", flat, re.IGNORECASE):
            return "inclusive", rate
        inclusive = bool(_INCLUSIVE_RE.search(text or ""))
        exclusive = bool(_EXCLUSIVE_RE.search(text or ""))
        if inclusive and not exclusive:
            return "inclusive", rate
        if exclusive and not inclusive:
            return "exclusive", rate
        return "unknown", rate

    @classmethod
    def _invoice_number(cls, text):
        match = _INVOICE_NO_RE.search(text or "")
        if not match:
            return None
        number = match.group(1).strip(" -:")
        if number.lower() in {"date", "no", "number", "tax"}:
            return None
        return number

    @classmethod
    def _invoice_date(cls, text):
        for line in (text or "").split("\n"):
            if not re.search(r"\bdate\b", line, re.IGNORECASE):
                continue
            match = _DATE_RE.search(line)
            if not match:
                continue
            parsed = cls._parse_date(match.group(1))
            if parsed:
                return parsed
        head = (text or "").split("Due Date")[0]
        match = _MONTH_DATE_RE.search(head)
        if match:
            return cls._parse_date(match.group(1))
        return None

    @classmethod
    def _parse_date(cls, token):
        token = re.sub(r"\s+", " ", (token or "").strip())
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(token, fmt).date()
            except ValueError:
                continue
        return None

    @classmethod
    def _supplier_hint(cls, text):
        """First short line that looks like a business name, for matching later."""
        for line in (text or "").split("\n"):
            candidate = re.sub(r"\s+", " ", line).strip(" -:|")
            if len(candidate) < 4 or len(candidate) > 60:
                continue
            if _FOOTER_RE.match(candidate) or _NOT_A_SUPPLIER.match(candidate):
                continue
            if _MONEY_RE.search(candidate) or re.search(r"\d{3,}", candidate):
                continue
            letters = re.sub(r"[^A-Za-z]", "", candidate)
            if len(letters) < 4:
                continue
            return candidate
        return None

    @classmethod
    def _printed_subtotal(cls, text, lines):
        """The ex-tax subtotal printed on the invoice, when it can be told apart from the line amounts."""
        line_totals = set()
        for row in lines or []:
            total = round((row.get("quantity") or 0.0) * (row.get("unit_price") or 0.0), 2)
            if total:
                line_totals.add(total)
        flat = re.sub(r"\s+", " ", text or "")
        same_line = re.search(
            r"sub\s*total[^\d]{0,30}((?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})",
            flat,
            re.IGNORECASE,
        )
        if same_line:
            return _to_float(same_line.group(1).replace(",", ""))
        marker = re.search(r"sub\s*total", text or "", re.IGNORECASE)
        if not marker:
            return None
        tail = re.sub(r"(?<=\d),(?=\d{3}\b)", "", (text or "")[marker.end() :])
        amounts = []
        for match in _MONEY_RE.finditer(tail):
            whole = match.group(1).replace(" ", "").replace("\u00a0", "")
            amount = _to_float(f"{whole}.{match.group(3)}")
            if amount is None:
                continue
            amounts.append(round(amount, 2))
            if len(amounts) >= 12:
                break
        extras = [amount for amount in amounts if amount not in line_totals]
        return extras[0] if extras else None

    @classmethod
    def _parse_column_blocks(cls, text):
        """Rebuild rows when each field of a line was extracted on its own line."""
        items = []
        current = None

        def flush():
            nonlocal current
            if not current:
                return
            item = cls._item_from_block(current)
            if item:
                items.append(item)
            current = None

        for raw_line in (text or "").split("\n"):
            line = re.sub(r"\s+", " ", raw_line.replace("\u00a0", " ")).strip()
            if not line:
                continue
            # Stop at the totals, not at a header word such as "VAT" above the table.
            if re.match(
                r"^(sub\s*total|grand\s+total|total\b|\d{1,2}%\s+vat\b)",
                line,
                re.IGNORECASE,
            ):
                flush()
                break
            if _CODE_LINE_RE.match(line):
                flush()
                current = [line]
                continue
            if current is None:
                continue
            if cls._block_ready(current) and _INT_LINE_RE.match(line):
                flush()
                continue
            current.append(line)
        flush()
        return items

    @classmethod
    def _block_ready(cls, lines):
        has_qty = has_price = has_desc = False
        for line in lines[1:]:
            if _INT_LINE_RE.match(line):
                has_qty = True
            elif _MONEY_LINE_RE.match(line):
                has_price = True
            elif not _ISO_DATE_LINE_RE.match(line) and not _LOT_LINE_RE.match(line):
                has_desc = True
        return has_qty and has_price and has_desc

    @classmethod
    def _item_from_block(cls, lines):
        code = lines[0]
        description_parts = []
        quantity = None
        prices = []
        extra_codes = [code]
        for line in lines[1:]:
            if _ISO_DATE_LINE_RE.match(line) or _LOT_LINE_RE.match(line):
                continue
            if _INT_LINE_RE.match(line) and quantity is None:
                quantity = float(line)
                continue
            if _MONEY_LINE_RE.match(line):
                prices.append(_to_float(line.replace(",", "")))
                continue
            paren = re.fullmatch(r"\((\d+)\)", line)
            if paren:
                extra_codes.append(paren.group(1))
            description_parts.append(line)
        description = re.sub(r"\s+", " ", " ".join(description_parts)).strip(" -")
        if not description or quantity is None or not prices:
            return None
        codes = []
        for token in extra_codes:
            if token not in codes:
                codes.append(token)
        return {
            "description": description,
            "quantity": quantity,
            "unit_price": prices[0],
            "codes": codes,
        }

    @classmethod
    def _parse_line(cls, raw_line):
        line = re.sub(r"\s+", " ", (raw_line or "").replace("\u00a0", " ")).strip()
        if len(line) < 3 or _FOOTER_RE.match(line):
            return None
        amounts = list(_MONEY_RE.finditer(line))
        if not amounts or len(amounts) > 4:
            return None
        values = []
        for match in amounts:
            whole = match.group(1).replace(" ", "").replace("\u00a0", "")
            parsed = _to_float(f"{whole}{match.group(2)}{match.group(3)}")
            if parsed is None:
                return None
            values.append(parsed)
        text = line
        for match in reversed(amounts):
            text = f"{text[: match.start()]} {text[match.end() :]}"
        text = re.sub(r"\s+", " ", text).strip(" -:|")
        unit = values[-2] if len(values) >= 2 else values[-1]
        total = values[-1] if len(values) >= 2 else None
        quantity = cls._quantity(text, unit, total)
        if quantity is None:
            return None
        description = cls._strip_quantity(text, quantity)
        if len(description) < 3:
            return None
        codes = []
        for token in _CODE_RE.findall(description.upper()):
            if any(char.isdigit() for char in token) and token not in codes:
                codes.append(token)
        return {
            "description": description,
            "quantity": quantity,
            "unit_price": unit,
            "codes": codes,
        }

    @classmethod
    def _quantity(cls, text, unit, total):
        trailing = re.search(r"(?:^|\s)(\d+(?:[.,]\d+)?)(?:\s*[xX])?\s*$", text or "")
        if trailing:
            qty = _to_float(trailing.group(1))
            if qty and 0 < qty <= 100000 and not cls._same_as_price(qty, unit):
                return qty
        leading = re.match(r"^(\d+(?:[.,]\d+)?)\s+\S", text or "")
        if leading:
            qty = _to_float(leading.group(1))
            if qty and 0 < qty <= 100000 and not cls._same_as_price(qty, unit):
                return qty
        if unit and total and unit > 0:
            guessed = total / unit
            rounded = round(guessed)
            if 0 < rounded <= 100000 and abs(guessed - rounded) < 0.02:
                return float(rounded)
        if re.search(r"[A-Za-z]{3,}", text or ""):
            return 1.0
        return None

    @classmethod
    def _strip_quantity(cls, text, quantity):
        qty_token = str(int(quantity)) if float(quantity).is_integer() else str(quantity)
        patterns = (
            rf"(?:^|\s){re.escape(qty_token)}(?:[.,]0+)?(?:\s*[xX])?\s*$",
            rf"^{re.escape(qty_token)}(?:[.,]0+)?\s+",
        )
        cleaned = text
        for pattern in patterns:
            updated = re.sub(pattern, " ", cleaned).strip()
            if updated != cleaned:
                cleaned = updated
                break
        return re.sub(r"\s+", " ", cleaned).strip(" -:|")

    @classmethod
    def _same_as_price(cls, qty, unit):
        return bool(unit) and abs(qty - unit) < 0.001

    @classmethod
    def _pdf_text(cls, raw_bytes):
        buffer = io.BytesIO(raw_bytes)
        try:
            from pdfminer.high_level import extract_text

            return extract_text(buffer) or ""
        except ImportError:
            buffer.seek(0)
        try:
            import PyPDF2
        except ImportError:
            return ""
        try:
            reader = PyPDF2.PdfReader(buffer)
        except Exception:
            return ""
        if getattr(reader, "is_encrypted", False):
            raise ValueError("This PDF is password-protected.")
        return "\n".join((page.extract_text() or "") for page in reader.pages)

    @classmethod
    def _ocr_image(cls, raw_bytes, suffix):
        cls._require_tesseract()
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / f"invoice{suffix or '.png'}"
            image.write_bytes(raw_bytes)
            return cls._tesseract(image)

    @classmethod
    def _ocr_pdf(cls, raw_bytes):
        cls._require_tesseract()
        if not shutil.which("pdftoppm"):
            raise ValueError(
                "This PDF is a scan. The server can read it once poppler "
                "(pdftoppm) is installed next to Tesseract."
            )
        with tempfile.TemporaryDirectory() as folder:
            pdf_path = Path(folder) / "invoice.pdf"
            pdf_path.write_bytes(raw_bytes)
            prefix = Path(folder) / "page"
            subprocess.run(
                ["pdftoppm", "-png", "-r", "200", str(pdf_path), str(prefix)],
                check=True,
                capture_output=True,
            )
            pages = sorted(Path(folder).glob("page*.png"))
            if not pages:
                raise ValueError("The scan could not be turned into images to read.")
            return "\n".join(cls._tesseract(page) for page in pages)

    @classmethod
    def _require_tesseract(cls):
        if shutil.which("tesseract"):
            return
        raise ValueError(
            "This looks like a scan or photo. Built-in OCR (Tesseract) is not "
            "installed on this server yet, so only a digital PDF can be read."
        )

    @classmethod
    def _tesseract(cls, image_path):
        result = subprocess.run(
            ["tesseract", str(image_path), "stdout", "-l", "eng", "--psm", "6"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or "").strip().split("\n")[-1:] or ["OCR failed"]
            raise ValueError(detail[0])
        return result.stdout or ""


def document_bytes(value):
    """Odoo binary fields are base64 text. Accept bytes too."""
    if not value:
        return b""
    raw = value.encode() if isinstance(value, str) else value
    try:
        return base64.b64decode(raw, validate=True)
    except Exception:
        return raw
