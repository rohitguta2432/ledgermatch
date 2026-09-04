"""Run the bundled demo end to end and record the run as events.jsonl.

    .venv/bin/python run_demo.py [path/to/events.jsonl]

The console page replays that file. Nothing in it is synthesized: every line is
an event the engine emitted, stamped with milliseconds since the run began.
"""

from __future__ import annotations

import sys

import sample_data
from matcher import reconcile
from normalize import PARSERS
from payouts import EventLog, reconcile_payouts


def main(out: str = "events.jsonl") -> None:
    samples = sample_data.generate()
    log = EventLog()
    log("run_start", files=["orders.csv", "stripe.csv", "square.csv", "paypal.csv", "bank.csv"])

    orders = PARSERS["orders"](samples["orders"])
    log("load", file="orders.csv", source="orders", rows=len(orders))
    payments: list[dict] = []
    for source in ("stripe", "square", "paypal"):
        rows = PARSERS[source](samples[source])
        payments.extend(rows)
        log("load", file=f"{source}.csv", source=source, rows=len(rows))
    bank = PARSERS["bank"](samples["bank"])
    log("load", file="bank.csv", source="bank", rows=len(bank))

    report = reconcile(orders, payments, emit=log)
    payouts = reconcile_payouts(payments, bank, emit=log)
    log.write(out)

    s, ps = report["summary"], payouts["summary"]
    print(f"orders   {s['matched']}/{s['orders_total']} matched ({s['match_rate']}%) · {s['exceptions']} exceptions · at risk {s['total_at_risk']:.2f}")
    print(f"payouts  {ps['payouts_landed']}/{ps['payouts_expected']} landed · {ps['payouts_short']} short · {ps['payouts_missing']} missing · cash gap {ps['cash_gap']:.2f}")
    print(f"events   {len(log.events)} written to {out} · run took {log.events[-1]['t']:.1f} ms")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "events.jsonl")
