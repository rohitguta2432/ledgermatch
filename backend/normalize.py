"""CSV normalization for payment processor exports.

Each parser accepts raw CSV text and returns a list of normalized Payment
dicts. Column names vary between processor export versions, so parsers
resolve columns by fuzzy header lookup rather than fixed position.

Normalized payment shape:
    {
        "id": str,          # processor transaction id
        "source": str,      # stripe | square | paypal
        "date": str,        # ISO date (YYYY-MM-DD)
        "gross": float,     # amount charged to customer
        "fee": float,       # processor fee (positive number)
        "net": float,       # gross - fee
        "currency": str,
        "ref": str,         # order reference if the processor carried one
        "description": str,
        "kind": str,        # charge | refund
    }
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime

from payouts import source_hint


def _to_float(value: str) -> float:
    if value is None:
        return 0.0
    cleaned = re.sub(r"[^0-9.\-]", "", str(value).replace(",", ""))
    if cleaned in ("", "-", "."):
        return 0.0
    return float(cleaned)


def _to_iso_date(value: str) -> str:
    value = (value or "").strip()
    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%d-%b-%Y",
        "%b %d, %Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    # ISO-ish fallback: take the leading date portion if present
    match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    if match:
        return match.group(1)
    return value


def _find_column(fieldnames: list[str], *candidates: str) -> str | None:
    """Return the first header whose lowercase form contains a candidate."""
    lowered = {name.lower().strip(): name for name in fieldnames}
    for candidate in candidates:
        for low, original in lowered.items():
            if candidate == low:
                return original
    for candidate in candidates:
        for low, original in lowered.items():
            if candidate in low:
                return original
    return None


def _rows(csv_text: str) -> tuple[list[dict], list[str]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = reader.fieldnames or []
    return list(reader), fieldnames


ORDER_REF_PATTERN = re.compile(r"(#?\d{4,}|[A-Z]{2,}-\d+)")


def _extract_ref(*texts: str) -> str:
    for text in texts:
        if not text:
            continue
        match = ORDER_REF_PATTERN.search(text)
        if match:
            return match.group(0).lstrip("#")
    return ""


def parse_stripe(csv_text: str) -> list[dict]:
    rows, headers = _rows(csv_text)
    col_id = _find_column(headers, "id")
    col_date = _find_column(headers, "created (utc)", "created", "date")
    col_gross = _find_column(headers, "amount")
    col_fee = _find_column(headers, "fee")
    col_currency = _find_column(headers, "currency")
    col_desc = _find_column(headers, "description")
    col_status = _find_column(headers, "status", "type")

    payments = []
    for row in rows:
        status = (row.get(col_status, "") or "").lower() if col_status else ""
        if status in ("failed", "canceled", "cancelled"):
            continue
        gross = _to_float(row.get(col_gross, "0"))
        fee = abs(_to_float(row.get(col_fee, "0")))
        kind = "refund" if gross < 0 or "refund" in status else "charge"
        description = row.get(col_desc, "") or ""
        payments.append({
            "id": row.get(col_id, "") or "",
            "source": "stripe",
            "date": _to_iso_date(row.get(col_date, "")),
            "gross": round(gross, 2),
            "fee": round(fee, 2),
            "net": round(gross - fee if kind == "charge" else gross + fee, 2),
            "currency": (row.get(col_currency, "usd") or "usd").upper(),
            "ref": _extract_ref(description),
            "description": description,
            "kind": kind,
        })
    return payments


def parse_square(csv_text: str) -> list[dict]:
    rows, headers = _rows(csv_text)
    col_id = _find_column(headers, "transaction id", "payment id", "id")
    col_date = _find_column(headers, "date")
    col_gross = _find_column(headers, "gross sales", "gross", "total collected")
    col_fee = _find_column(headers, "fees", "fee")
    col_desc = _find_column(headers, "description", "details", "notes")
    col_currency = _find_column(headers, "currency")

    payments = []
    for row in rows:
        gross = _to_float(row.get(col_gross, "0"))
        fee = abs(_to_float(row.get(col_fee, "0")))
        kind = "refund" if gross < 0 else "charge"
        description = row.get(col_desc, "") or ""
        payments.append({
            "id": row.get(col_id, "") or "",
            "source": "square",
            "date": _to_iso_date(row.get(col_date, "")),
            "gross": round(gross, 2),
            "fee": round(fee, 2),
            "net": round(gross - fee if kind == "charge" else gross + fee, 2),
            "currency": (row.get(col_currency, "usd") or "usd").upper(),
            "ref": _extract_ref(description),
            "description": description,
            "kind": kind,
        })
    return payments


def parse_paypal(csv_text: str) -> list[dict]:
    rows, headers = _rows(csv_text)
    col_id = _find_column(headers, "transaction id", "id")
    col_date = _find_column(headers, "date")
    col_gross = _find_column(headers, "gross")
    col_fee = _find_column(headers, "fee")
    col_currency = _find_column(headers, "currency")
    col_invoice = _find_column(headers, "invoice number", "invoice id", "invoice")
    col_name = _find_column(headers, "name", "description")
    col_type = _find_column(headers, "type")

    payments = []
    for row in rows:
        row_type = (row.get(col_type, "") or "").lower() if col_type else ""
        if any(word in row_type for word in ("withdrawal", "transfer", "hold", "fee reversal")):
            continue
        gross = _to_float(row.get(col_gross, "0"))
        fee = abs(_to_float(row.get(col_fee, "0")))
        kind = "refund" if gross < 0 or "refund" in row_type else "charge"
        invoice = row.get(col_invoice, "") if col_invoice else ""
        description = row.get(col_name, "") or ""
        payments.append({
            "id": row.get(col_id, "") or "",
            "source": "paypal",
            "date": _to_iso_date(row.get(col_date, "")),
            "gross": round(gross, 2),
            "fee": round(fee, 2),
            "net": round(gross - fee if kind == "charge" else gross + fee, 2),
            "currency": (row.get(col_currency, "usd") or "usd").upper(),
            "ref": _extract_ref(invoice, description),
            "description": description,
            "kind": kind,
        })
    return payments


def parse_orders(csv_text: str) -> list[dict]:
    """Store/order-system export: the merchant's source of truth."""
    rows, headers = _rows(csv_text)
    col_id = _find_column(headers, "order id", "order", "name", "id")
    col_date = _find_column(headers, "date", "created at", "created")
    col_amount = _find_column(headers, "total", "amount", "gross")
    col_currency = _find_column(headers, "currency")
    col_customer = _find_column(headers, "customer", "email", "billing name")

    orders = []
    for row in rows:
        order_id = (row.get(col_id, "") or "").lstrip("#")
        orders.append({
            "order_id": order_id,
            "date": _to_iso_date(row.get(col_date, "")),
            "amount": round(_to_float(row.get(col_amount, "0")), 2),
            "currency": (row.get(col_currency, "usd") or "usd").upper(),
            "customer": row.get(col_customer, "") or "",
        })
    return [o for o in orders if o["order_id"]]


def parse_bank(csv_text: str) -> list[dict]:
    """Bank statement export: one line per credit or debit.

    Normalized bank line shape:
        {
            "id": str,            # statement reference, or a stable row number
            "date": str,          # ISO date
            "description": str,
            "amount": float,      # credits positive, debits negative
            "balance": float | None,
            "source_hint": str,   # stripe | square | paypal | '' (from the description)
        }
    """
    rows, headers = _rows(csv_text)
    col_date = _find_column(headers, "date", "posted", "transaction date")
    col_desc = _find_column(headers, "description", "memo", "details", "narrative", "payee")
    col_amount = _find_column(headers, "amount")
    col_credit = _find_column(headers, "credit", "deposit", "money in", "paid in")
    col_debit = _find_column(headers, "debit", "withdrawal", "money out", "paid out")
    col_balance = _find_column(headers, "balance")
    col_id = _find_column(headers, "reference", "transaction id", "ref")

    lines = []
    for i, row in enumerate(rows, start=1):
        if col_amount:
            amount = _to_float(row.get(col_amount, "0"))
        else:
            credit = _to_float(row.get(col_credit, "0")) if col_credit else 0.0
            debit = abs(_to_float(row.get(col_debit, "0"))) if col_debit else 0.0
            amount = credit - debit
        description = (row.get(col_desc, "") or "").strip() if col_desc else ""
        line_id = (row.get(col_id, "") or "").strip() if col_id else ""
        raw_balance = row.get(col_balance, "") if col_balance else ""
        lines.append({
            "id": line_id or f"bank-{i:04d}",
            "date": _to_iso_date(row.get(col_date, "")),
            "description": description,
            "amount": round(amount, 2),
            "balance": _to_float(raw_balance) if raw_balance not in (None, "") else None,
            "source_hint": source_hint(description),
        })
    return lines


PARSERS = {
    "stripe": parse_stripe,
    "square": parse_square,
    "paypal": parse_paypal,
    "orders": parse_orders,
    "bank": parse_bank,
}


def detect_source(filename: str, csv_text: str) -> str | None:
    """Guess the source from filename, then headers."""
    name = (filename or "").lower()
    for source in ("stripe", "square", "paypal", "order", "bank", "statement"):
        if source in name:
            return {"order": "orders", "statement": "bank"}.get(source, source)
    header_line = csv_text.splitlines()[0].lower() if csv_text else ""
    if "balance transaction" in header_line or "converted amount" in header_line:
        return "stripe"
    if "gross sales" in header_line:
        return "square"
    if "invoice number" in header_line or ("gross" in header_line and "name" in header_line):
        return "paypal"
    looks_like_money = any(w in header_line for w in ("amount", "credit", "debit", "deposit"))
    has_processor_columns = "gross" in header_line or "fee" in header_line
    if "balance" in header_line or (
        ("description" in header_line or "memo" in header_line) and looks_like_money and not has_processor_columns
    ):
        return "bank"
    if "order" in header_line or "customer" in header_line:
        return "orders"
    return None
