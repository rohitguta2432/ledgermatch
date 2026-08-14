"""Generate realistic sample CSVs for the demo.

Deterministic (seeded) so the demo numbers are stable across runs.
Plants known exceptions:
  - 2 orders with no payment (missing money)
  - 1 Stripe payment with an amount mismatch vs its order
  - 1 orphan Square payment with no order
  - 1 unlinked PayPal refund
"""

from __future__ import annotations

import csv
import io
import random
from datetime import date, timedelta

SEED = 20260814
BASE_DATE = date(2026, 7, 15)

FIRST_NAMES = [
    "Aisha", "Marco", "Priya", "Daniel", "Sofia", "Liam", "Nina", "Omar",
    "Grace", "Hiro", "Elena", "Jack", "Maya", "Noah", "Zara", "Felix",
]
LAST_NAMES = [
    "Khan", "Rossi", "Patel", "Kim", "Garcia", "Smith", "Ivanova", "Ali",
    "Chen", "Tanaka", "Novak", "Brown", "Iyer", "Muller", "Costa", "Wright",
]


def _stripe_fee(amount: float) -> float:
    return round(amount * 0.029 + 0.30, 2)


def _square_fee(amount: float) -> float:
    return round(amount * 0.026 + 0.10, 2)


def _paypal_fee(amount: float) -> float:
    return round(amount * 0.0349 + 0.49, 2)


def generate() -> dict[str, str]:
    rng = random.Random(SEED)

    orders = []
    for i in range(48):
        order_id = str(1001 + i)
        day = BASE_DATE + timedelta(days=rng.randint(0, 20))
        amount = round(rng.uniform(18, 420), 2)
        customer = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        source = rng.choices(["stripe", "square", "paypal"], weights=[5, 3, 2])[0]
        orders.append({
            "order_id": order_id,
            "date": day,
            "amount": amount,
            "customer": customer,
            "source": source,
        })

    # Planted exceptions
    missing_payment_ids = {orders[7]["order_id"], orders[31]["order_id"]}
    mismatch_id = orders[14]["order_id"]

    stripe_rows, square_rows, paypal_rows = [], [], []
    for order in orders:
        if order["order_id"] in missing_payment_ids:
            continue
        pay_date = order["date"] + timedelta(days=rng.randint(0, 2))
        amount = order["amount"]
        if order["order_id"] == mismatch_id:
            amount = round(amount - 18.00, 2)  # partial capture — mismatch

        if order["source"] == "stripe":
            stripe_rows.append({
                "id": f"ch_{rng.randrange(10**14):014x}",
                "Created (UTC)": f"{pay_date} {rng.randint(8, 22):02d}:{rng.randint(0, 59):02d}:00",
                "Amount": f"{amount:.2f}",
                "Fee": f"{_stripe_fee(amount):.2f}",
                "Currency": "usd",
                "Status": "Paid",
                "Description": f"Payment for order #{order['order_id']}",
            })
        elif order["source"] == "square":
            square_rows.append({
                "Transaction ID": f"sq_{rng.randrange(10**12):012d}",
                "Date": str(pay_date),
                "Gross Sales": f"{amount:.2f}",
                "Fees": f"{_square_fee(amount):.2f}",
                "Currency": "USD",
                "Description": f"Order #{order['order_id']}" if rng.random() < 0.7 else "Card payment",
            })
        else:
            paypal_rows.append({
                "Date": str(pay_date),
                "Name": order["customer"],
                "Type": "Express Checkout Payment",
                "Gross": f"{amount:.2f}",
                "Fee": f"{_paypal_fee(amount):.2f}",
                "Currency": "USD",
                "Transaction ID": f"pp_{rng.randrange(10**13):013d}",
                "Invoice Number": order["order_id"],
            })

    # Orphan Square payment (no order behind it)
    square_rows.append({
        "Transaction ID": f"sq_{rng.randrange(10**12):012d}",
        "Date": str(BASE_DATE + timedelta(days=9)),
        "Gross Sales": "87.50",
        "Fees": f"{_square_fee(87.50):.2f}",
        "Currency": "USD",
        "Description": "Card payment",
    })

    # Unlinked PayPal refund
    paypal_rows.append({
        "Date": str(BASE_DATE + timedelta(days=16)),
        "Name": "Chris Doyle",
        "Type": "Payment Refund",
        "Gross": "-64.00",
        "Fee": "0.00",
        "Currency": "USD",
        "Transaction ID": f"pp_{rng.randrange(10**13):013d}",
        "Invoice Number": "",
    })

    def to_csv(rows: list[dict]) -> str:
        if not rows:
            return ""
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue()

    orders_csv_rows = [
        {
            "Order ID": f"#{o['order_id']}",
            "Date": str(o["date"]),
            "Customer": o["customer"],
            "Total": f"{o['amount']:.2f}",
            "Currency": "USD",
        }
        for o in orders
    ]

    return {
        "orders": to_csv(orders_csv_rows),
        "stripe": to_csv(stripe_rows),
        "square": to_csv(square_rows),
        "paypal": to_csv(paypal_rows),
    }


if __name__ == "__main__":
    import pathlib

    out_dir = pathlib.Path(__file__).parent / "sample_data"
    out_dir.mkdir(exist_ok=True)
    for name, text in generate().items():
        (out_dir / f"{name}.csv").write_text(text)
        print(f"wrote sample_data/{name}.csv ({len(text.splitlines()) - 1} rows)")
