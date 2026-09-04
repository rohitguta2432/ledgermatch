"""Payout reconciliation: processor payouts <-> bank statement.

Processors settle in batches. Every charge belongs to a payout that lands in
the bank a few days later as one lump sum, minus fees and refunds. Matching
orders to charges (matcher.py) proves the customer paid; this module proves
the money actually reached the bank.

  1. reconstruct the expected payouts from charges and refunds
     (per processor, per settlement date, using each processor's lag)
  2. match every expected payout to a bank credit
       exact     same net amount, date within the window
       combined  several consecutive payouts landing as one credit
       short     it landed, but not for the full amount
  3. flag what went wrong
       payout_missing       expected money never hit the bank
       payout_short         landed short (reserve hold, chargeback, fee change)
       unexplained_deposit  a processor credit with no payout behind it

Every step calls `emit(kind, **fields)`, so a run can be recorded to
events.jsonl and replayed in the console exactly as it happened.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from itertools import combinations
from time import perf_counter
from typing import Callable

SETTLEMENT_LAG_DAYS = {"stripe": 2, "square": 1, "paypal": 0}
DEFAULT_LAG_DAYS = 1
DATE_WINDOW_DAYS = 3
AMOUNT_TOLERANCE = 0.02
MAX_COMBINE = 4
SHORT_RATIO = (0.5, 1.2)  # a credit outside this share of the expected net is not "the same payout"

BANK_HINTS = {
    "stripe": ("stripe",),
    "square": ("square", "sq *", "sqc*"),
    "paypal": ("paypal",),
}

Emit = Callable[..., None]


def _noop(kind: str, **fields) -> None:  # noqa: ARG001 - default sink
    return None


class EventLog:
    """Timestamped event sink. `t` is milliseconds since the log was opened."""

    def __init__(self) -> None:
        self.t0 = perf_counter()
        self.events: list[dict] = []

    def __call__(self, kind: str, **fields) -> None:
        self.events.append({"t": round((perf_counter() - self.t0) * 1000, 3), "kind": kind, **fields})

    def write(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            for event in self.events:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _dates_close(a: str, b: str, days: int = DATE_WINDOW_DAYS) -> bool:
    da, db = _parse_date(a), _parse_date(b)
    if da is None or db is None:
        return True
    return abs(da - db) <= timedelta(days=days)


def source_hint(description: str) -> str:
    """Which processor a bank line's description points at, or ''."""
    text = (description or "").lower()
    for source, hints in BANK_HINTS.items():
        if any(hint in text for hint in hints):
            return source
    return ""


def expected_payouts(payments: list[dict], emit: Emit = _noop) -> list[dict]:
    """Group charges and refunds into the payouts the processor should have sent."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for payment in payments:
        paid_on = _parse_date(payment["date"])
        if paid_on is None:
            emit("skip", source=payment["source"], id=payment["id"], reason="unparseable date")
            continue
        lag = SETTLEMENT_LAG_DAYS.get(payment["source"], DEFAULT_LAG_DAYS)
        settle = (paid_on + timedelta(days=lag)).isoformat()
        groups.setdefault((payment["source"], settle), []).append(payment)

    payouts = []
    for (source, settle), items in sorted(groups.items()):
        charges = [i for i in items if i["kind"] == "charge"]
        refunds = [i for i in items if i["kind"] != "charge"]
        gross = round(sum(c["gross"] for c in charges), 2)
        fees = round(sum(c["fee"] for c in charges), 2)
        refunded = round(sum(-r["gross"] for r in refunds), 2)
        net = round(sum(i["net"] for i in items), 2)
        payouts.append({
            "id": f"{source}-{settle}",
            "source": source,
            "date": settle,
            "charges": len(charges),
            "refunds": len(refunds),
            "gross": gross,
            "fees": fees,
            "refunded": refunded,
            "net": net,
            "status": "expected" if net > AMOUNT_TOLERANCE else "nothing_due",
            "bank": None,
            "delta": 0.0,
        })
        emit("payout", source=source, date=settle, charges=len(charges), refunds=len(refunds),
             gross=gross, fees=fees, net=net)
    return payouts


def _link(payout: dict, credit: dict, status: str, used: set[str]) -> None:
    payout["status"] = status
    payout["bank"] = {"id": credit["id"], "date": credit["date"],
                      "description": credit["description"], "amount": credit["amount"]}
    payout["delta"] = round(credit["amount"] - payout["net"], 2)
    used.add(credit["id"])


def reconcile_payouts(payments: list[dict], bank_lines: list[dict], emit: Emit = _noop) -> dict:
    emit("payouts_start", payments=len(payments))
    payouts = expected_payouts(payments, emit)
    credits = [b for b in bank_lines if b["amount"] > 0]
    processor_credits = [c for c in credits if c["source_hint"]]
    emit("bank", lines=len(bank_lines), credits=len(credits), processor_credits=len(processor_credits))

    used: set[str] = set()
    open_payouts = [p for p in payouts if p["status"] == "expected"]

    def candidates(payout: dict, days: int = DATE_WINDOW_DAYS) -> list[dict]:
        return [
            c for c in credits
            if c["id"] not in used
            and c["source_hint"] in (payout["source"], "")
            and _dates_close(c["date"], payout["date"], days)
        ]

    # Pass 1: exact net amount within the date window (processor-tagged credits first)
    for payout in open_payouts:
        hits = [c for c in candidates(payout) if abs(c["amount"] - payout["net"]) <= AMOUNT_TOLERANCE]
        if not hits:
            continue
        credit = min(hits, key=lambda c: (c["source_hint"] == "", abs(c["amount"] - payout["net"]), c["date"]))
        _link(payout, credit, "landed", used)
        emit("landed", source=payout["source"], date=payout["date"], net=payout["net"],
             bank_id=credit["id"], bank_date=credit["date"], description=credit["description"])

    # Pass 2: one credit covering several consecutive payouts (processor batched them)
    for credit in processor_credits:
        if credit["id"] in used:
            continue
        pool = sorted(
            (p for p in open_payouts
             if p["status"] == "expected" and p["source"] == credit["source_hint"]
             and _dates_close(p["date"], credit["date"], DATE_WINDOW_DAYS + MAX_COMBINE)),
            key=lambda p: p["date"],
        )
        found = None
        for size in range(2, min(MAX_COMBINE, len(pool)) + 1):
            for combo in combinations(pool, size):
                if abs(sum(p["net"] for p in combo) - credit["amount"]) <= AMOUNT_TOLERANCE:
                    found = combo
                    break
            if found:
                break
        if not found:
            continue
        for payout in found:
            _link(payout, credit, "landed", used)
            payout["combined_with"] = [p["id"] for p in found if p is not payout]
            payout["delta"] = 0.0
        emit("combined", source=credit["source_hint"], dates=[p["date"] for p in found],
             nets=[p["net"] for p in found], bank_id=credit["id"], bank_date=credit["date"],
             amount=credit["amount"], description=credit["description"])

    # Pass 3: landed, but not for the full amount
    for payout in open_payouts:
        if payout["status"] != "expected":
            continue
        low, high = SHORT_RATIO
        hits = [c for c in candidates(payout) if c["source_hint"] == payout["source"]
                and low * payout["net"] <= c["amount"] <= high * payout["net"]]
        if not hits:
            continue
        credit = min(hits, key=lambda c: abs(c["amount"] - payout["net"]))
        _link(payout, credit, "short" if credit["amount"] < payout["net"] else "over", used)
        emit(payout["status"], source=payout["source"], date=payout["date"], net=payout["net"],
             amount=credit["amount"], delta=payout["delta"], bank_id=credit["id"],
             bank_date=credit["date"], description=credit["description"])

    # Whatever is still open never arrived
    for payout in open_payouts:
        if payout["status"] == "expected":
            payout["status"] = "missing"
            emit("missing", source=payout["source"], date=payout["date"], net=payout["net"],
                 charges=payout["charges"])

    unexplained = [c for c in processor_credits if c["id"] not in used]
    for credit in unexplained:
        emit("unexplained", source=credit["source_hint"], bank_id=credit["id"], date=credit["date"],
             amount=credit["amount"], description=credit["description"])

    exceptions = _exceptions(payouts, unexplained)
    landed = [p for p in payouts if p["status"] == "landed"]
    short = [p for p in payouts if p["status"] == "short"]
    missing = [p for p in payouts if p["status"] == "missing"]
    cash_gap = round(sum(p["net"] for p in missing) + sum(-p["delta"] for p in short), 2)
    summary = {
        "payouts_expected": len(open_payouts),
        "payouts_landed": len(landed),
        "payouts_short": len(short),
        "payouts_missing": len(missing),
        "bank_lines": len(bank_lines),
        "bank_credits": len(credits),
        "bank_unexplained": len(unexplained),
        "cash_gap": cash_gap,
    }
    emit("run_end", **summary)
    return {"payouts": payouts, "unexplained": unexplained, "exceptions": exceptions, "summary": summary}


def _exceptions(payouts: list[dict], unexplained: list[dict]) -> list[dict]:
    exceptions = []
    for payout in payouts:
        name = payout["source"].title()
        breakdown = (
            f"{payout['charges']} charges settling {payout['date']}: gross {payout['gross']:.2f} "
            f"− fees {payout['fees']:.2f}"
            + (f" − refunds {payout['refunded']:.2f}" if payout["refunded"] else "")
            + f" = {payout['net']:.2f} expected."
        )
        if payout["status"] == "missing":
            exceptions.append({
                "type": "payout_missing",
                "severity": "high",
                "title": f"{name} payout of {payout['net']:.2f} never reached the bank",
                "detail": breakdown + f" No bank credit within ±{DATE_WINDOW_DAYS} days.",
                "amount": payout["net"],
                "payout": payout,
            })
        elif payout["status"] == "short":
            bank = payout["bank"]
            exceptions.append({
                "type": "payout_short",
                "severity": "high",
                "title": f"{name} payout landed short by {-payout['delta']:.2f}",
                "detail": breakdown + (
                    f" Bank shows {bank['amount']:.2f} on {bank['date']} ({bank['description']}). "
                    "Reserve hold, chargeback or a fee change?"
                ),
                "amount": round(-payout["delta"], 2),
                "payout": payout,
            })
        elif payout["status"] == "over":
            bank = payout["bank"]
            exceptions.append({
                "type": "payout_over",
                "severity": "medium",
                "title": f"{name} payout landed over by {payout['delta']:.2f}",
                "detail": breakdown + f" Bank shows {bank['amount']:.2f} on {bank['date']} ({bank['description']}).",
                "amount": round(payout["delta"], 2),
                "payout": payout,
            })
    for credit in unexplained:
        exceptions.append({
            "type": "unexplained_deposit",
            "severity": "medium",
            "title": f"{credit['source_hint'].title()} deposit of {credit['amount']:.2f} with no payout behind it",
            "detail": (
                f"{credit['date']} {credit['description']} — no charges settle to this amount. "
                "Unrecorded sales, or another account's payout?"
            ),
            "amount": credit["amount"],
            "bank": credit,
        })
    return exceptions
