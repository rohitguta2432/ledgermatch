"""Reconciliation engine: match store orders against processor payments.

Matching passes, in order of confidence:
  1. ref     — the payment carries the order id (description / invoice field)
  2. exact   — same amount, date within ±3 days, unmatched on both sides
  3. fuzzy   — amount within $0.02 (rounding drift), date within ±3 days

Everything left over becomes an exception:
  - missing_payment   order with no payment found  -> money never arrived
  - orphan_payment    payment with no order        -> unrecorded revenue
  - amount_mismatch   ref-matched pair whose amounts disagree
  - unlinked_refund   refund with no matching original charge
"""

from __future__ import annotations

from datetime import date, timedelta

DATE_WINDOW_DAYS = 3
AMOUNT_TOLERANCE = 0.02


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _dates_close(a: str, b: str, days: int = DATE_WINDOW_DAYS) -> bool:
    da, db = _parse_date(a), _parse_date(b)
    if da is None or db is None:
        return True  # unparseable dates should not block a match
    return abs(da - db) <= timedelta(days=days)


def reconcile(orders: list[dict], payments: list[dict]) -> dict:
    charges = [p for p in payments if p["kind"] == "charge"]
    refunds = [p for p in payments if p["kind"] == "refund"]

    matches: list[dict] = []
    matched_order_ids: set[str] = set()
    matched_payment_keys: set[tuple] = set()

    def payment_key(p: dict) -> tuple:
        return (p["source"], p["id"])

    # Pass 1: explicit order reference carried by the payment
    orders_by_id = {o["order_id"]: o for o in orders}
    for payment in charges:
        ref = payment.get("ref", "")
        if not ref or ref not in orders_by_id:
            continue
        order = orders_by_id[ref]
        if order["order_id"] in matched_order_ids:
            continue
        confidence = "ref"
        delta = round(payment["gross"] - order["amount"], 2)
        matches.append({
            "order": order,
            "payment": payment,
            "confidence": confidence,
            "delta": delta,
        })
        matched_order_ids.add(order["order_id"])
        matched_payment_keys.add(payment_key(payment))

    # Pass 2: exact amount + close date
    for payment in charges:
        if payment_key(payment) in matched_payment_keys:
            continue
        candidates = [
            o for o in orders
            if o["order_id"] not in matched_order_ids
            and abs(o["amount"] - payment["gross"]) < 0.005
            and _dates_close(o["date"], payment["date"])
        ]
        if len(candidates) >= 1:
            order = min(candidates, key=lambda o: o["date"])
            matches.append({
                "order": order,
                "payment": payment,
                "confidence": "exact",
                "delta": 0.0,
            })
            matched_order_ids.add(order["order_id"])
            matched_payment_keys.add(payment_key(payment))

    # Pass 3: amount within tolerance (currency rounding drift)
    for payment in charges:
        if payment_key(payment) in matched_payment_keys:
            continue
        candidates = [
            o for o in orders
            if o["order_id"] not in matched_order_ids
            and abs(o["amount"] - payment["gross"]) <= AMOUNT_TOLERANCE
            and _dates_close(o["date"], payment["date"])
        ]
        if candidates:
            order = min(candidates, key=lambda o: abs(o["amount"] - payment["gross"]))
            matches.append({
                "order": order,
                "payment": payment,
                "confidence": "fuzzy",
                "delta": round(payment["gross"] - order["amount"], 2),
            })
            matched_order_ids.add(order["order_id"])
            matched_payment_keys.add(payment_key(payment))

    # Refunds: link to a matched charge by ref or amount
    unlinked_refunds = []
    for refund in refunds:
        linked = False
        for match in matches:
            payment = match["payment"]
            same_source = payment["source"] == refund["source"]
            ref_hit = refund.get("ref") and refund["ref"] == match["order"]["order_id"]
            amount_hit = abs(abs(refund["gross"]) - payment["gross"]) < 0.005
            if same_source and (ref_hit or amount_hit):
                match.setdefault("refunds", []).append(refund)
                linked = True
                break
        if not linked:
            unlinked_refunds.append(refund)

    # Exceptions
    exceptions = []
    for order in orders:
        if order["order_id"] not in matched_order_ids:
            exceptions.append({
                "type": "missing_payment",
                "severity": "high",
                "title": f"Order #{order['order_id']} has no payment",
                "detail": (
                    f"{order['customer'] or 'Customer'} order of "
                    f"{order['currency']} {order['amount']:.2f} on {order['date']} "
                    "was not found in any processor export."
                ),
                "amount": order["amount"],
                "order": order,
            })
    for payment in charges:
        if payment_key(payment) not in matched_payment_keys:
            exceptions.append({
                "type": "orphan_payment",
                "severity": "medium",
                "title": f"{payment['source'].title()} payment {payment['id']} has no order",
                "detail": (
                    f"{payment['currency']} {payment['gross']:.2f} received on "
                    f"{payment['date']} does not match any order — unrecorded revenue?"
                ),
                "amount": payment["gross"],
                "payment": payment,
            })
    for match in matches:
        if match["delta"] and abs(match["delta"]) > AMOUNT_TOLERANCE:
            exceptions.append({
                "type": "amount_mismatch",
                "severity": "high",
                "title": f"Order #{match['order']['order_id']} amount mismatch",
                "detail": (
                    f"Order says {match['order']['amount']:.2f} but "
                    f"{match['payment']['source']} charged {match['payment']['gross']:.2f} "
                    f"(delta {match['delta']:+.2f})."
                ),
                "amount": abs(match["delta"]),
                "order": match["order"],
                "payment": match["payment"],
            })
    for refund in unlinked_refunds:
        exceptions.append({
            "type": "unlinked_refund",
            "severity": "medium",
            "title": f"{refund['source'].title()} refund with no matching charge",
            "detail": (
                f"Refund of {refund['currency']} {abs(refund['gross']):.2f} on "
                f"{refund['date']} could not be tied to any matched order."
            ),
            "amount": abs(refund["gross"]),
            "payment": refund,
        })

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    exceptions.sort(key=lambda e: (severity_rank[e["severity"]], -e["amount"]))

    # Summary
    fees_by_source: dict[str, float] = {}
    gross_by_source: dict[str, float] = {}
    for payment in payments:
        fees_by_source[payment["source"]] = round(
            fees_by_source.get(payment["source"], 0.0) + payment["fee"], 2
        )
        gross_by_source[payment["source"]] = round(
            gross_by_source.get(payment["source"], 0.0) + payment["gross"], 2
        )

    total_at_risk = round(
        sum(e["amount"] for e in exceptions if e["type"] in ("missing_payment", "amount_mismatch")), 2
    )

    return {
        "summary": {
            "orders_total": len(orders),
            "payments_total": len(charges),
            "refunds_total": len(refunds),
            "matched": len(matches),
            "match_rate": round(len(matches) / len(orders) * 100, 1) if orders else 0.0,
            "exceptions": len(exceptions),
            "total_fees": round(sum(fees_by_source.values()), 2),
            "fees_by_source": fees_by_source,
            "gross_by_source": gross_by_source,
            "total_at_risk": total_at_risk,
        },
        "matches": matches,
        "exceptions": exceptions,
    }
