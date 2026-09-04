"""Payout reconciliation: processor payouts <-> bank statement."""

import sample_data
from matcher import reconcile
from normalize import PARSERS, detect_source, parse_bank
from payouts import expected_payouts, reconcile_payouts, source_hint


def charge(source, day, gross, fee, kind="charge", pid=None):
    net = round(gross - fee, 2) if kind == "charge" else round(gross + fee, 2)
    return {
        "id": pid or f"{source}-{day}-{gross}", "source": source, "date": day, "gross": gross,
        "fee": fee, "net": net, "currency": "USD", "ref": "", "description": "", "kind": kind,
    }


def bank(bid, day, description, amount):
    return {"id": bid, "date": day, "description": description, "amount": amount,
            "balance": None, "source_hint": source_hint(description)}


def test_expected_payouts_group_by_processor_and_settlement_day():
    pays = [
        charge("stripe", "2026-08-01", 100.0, 3.2),
        charge("stripe", "2026-08-01", 50.0, 1.75),
        charge("square", "2026-08-01", 80.0, 2.18),
    ]
    got = [(p["source"], p["date"], p["charges"], p["net"]) for p in expected_payouts(pays)]
    assert got == [("square", "2026-08-02", 1, 77.82), ("stripe", "2026-08-03", 2, 145.05)]


def test_refund_reduces_the_payout():
    pays = [charge("paypal", "2026-08-01", 100.0, 3.0), charge("paypal", "2026-08-01", -40.0, 0.0, kind="refund")]
    payout = expected_payouts(pays)[0]
    assert payout["net"] == 57.0 and payout["refunded"] == 40.0 and payout["charges"] == 1


def test_exact_landing_within_the_window():
    r = reconcile_payouts([charge("stripe", "2026-08-01", 100.0, 3.2)],
                          [bank("b1", "2026-08-04", "STRIPE TRANSFER ST-1", 96.80)])
    assert r["payouts"][0]["status"] == "landed"
    assert r["payouts"][0]["bank"]["id"] == "b1"
    assert r["summary"]["cash_gap"] == 0 and r["exceptions"] == []


def test_untagged_credit_can_still_land_a_payout():
    r = reconcile_payouts([charge("stripe", "2026-08-01", 100.0, 3.2)],
                          [bank("b1", "2026-08-03", "ACH CREDIT 4471", 96.80)])
    assert r["payouts"][0]["status"] == "landed"


def test_missing_payout_is_flagged_with_its_net():
    r = reconcile_payouts([charge("stripe", "2026-08-01", 100.0, 3.2)],
                          [bank("b1", "2026-08-03", "GUSTO PAYROLL", -4000.0)])
    assert r["payouts"][0]["status"] == "missing"
    exc = r["exceptions"][0]
    assert exc["type"] == "payout_missing" and exc["severity"] == "high" and exc["amount"] == 96.8
    assert r["summary"]["cash_gap"] == 96.8 and r["summary"]["payouts_missing"] == 1


def test_short_landing_reports_the_delta():
    r = reconcile_payouts([charge("square", "2026-08-01", 300.0, 7.9)],  # net 292.10
                          [bank("b1", "2026-08-02", "SQUARE INC DES:DEPOSIT", 247.10)])
    payout = r["payouts"][0]
    assert payout["status"] == "short" and payout["delta"] == -45.0
    assert r["exceptions"][0]["type"] == "payout_short" and r["exceptions"][0]["amount"] == 45.0
    assert r["summary"]["cash_gap"] == 45.0


def test_combined_deposit_covers_consecutive_payouts():
    pays = [charge("stripe", "2026-08-01", 100.0, 3.2), charge("stripe", "2026-08-02", 60.0, 2.04)]  # 96.80 + 57.96
    r = reconcile_payouts(pays, [bank("b1", "2026-08-04", "STRIPE TRANSFER ST-9", 154.76)])
    assert [p["status"] for p in r["payouts"]] == ["landed", "landed"]
    assert r["payouts"][0]["combined_with"] == [r["payouts"][1]["id"]]
    assert r["summary"]["payouts_landed"] == 2 and r["exceptions"] == []


def test_processor_deposit_with_no_payout_is_unexplained_but_other_credits_are_not():
    r = reconcile_payouts([], [bank("b1", "2026-08-04", "STRIPE TRANSFER ST-2", 500.0),
                               bank("b2", "2026-08-04", "ZELLE FROM J DOYLE", 500.0)])
    assert r["summary"]["bank_unexplained"] == 1
    assert [e["type"] for e in r["exceptions"]] == ["unexplained_deposit"]


def test_events_tell_the_whole_story_in_order():
    events = []
    reconcile_payouts([charge("stripe", "2026-08-01", 100.0, 3.2)], [],
                      emit=lambda kind, **fields: events.append(kind))
    assert events[0] == "payouts_start" and events[-1] == "run_end"
    assert "payout" in events and "missing" in events


def test_parse_bank_amount_column_and_source_hints():
    csv = ("Date,Description,Amount,Balance\n"
           "2026-08-04,STRIPE TRANSFER ST-1,96.80,1096.80\n"
           "2026-08-05,WEWORK RENT,-1800.00,-703.20\n")
    lines = parse_bank(csv)
    assert lines[0]["amount"] == 96.8 and lines[0]["source_hint"] == "stripe" and lines[0]["balance"] == 1096.8
    assert lines[1]["amount"] == -1800.0 and lines[1]["source_hint"] == ""


def test_parse_bank_credit_and_debit_columns():
    csv = ("Posted,Memo,Credit,Debit\n"
           "08/04/2026,SQ *COFFEE DEPOSIT,77.82,\n"
           "08/05/2026,AMEX EPAYMENT,,912.44\n")
    lines = parse_bank(csv)
    assert lines[0]["amount"] == 77.82 and lines[0]["source_hint"] == "square" and lines[0]["date"] == "2026-08-04"
    assert lines[1]["amount"] == -912.44


def test_detect_bank_statement_by_name_or_headers():
    assert detect_source("bank.csv", "x") == "bank"
    assert detect_source("august-statement.csv", "x") == "bank"
    assert detect_source("x.csv", "Date,Description,Amount,Balance\n") == "bank"
    assert detect_source("x.csv", "Order ID,Date,Customer,Total\n") == "orders"
    assert detect_source("x.csv", "id,Created (UTC),Amount,Fee,Currency,Status,Description\n") != "bank"


def _demo():
    samples = sample_data.generate()
    orders = PARSERS["orders"](samples["orders"])
    payments = [p for s in ("stripe", "square", "paypal") for p in PARSERS[s](samples[s])]
    return orders, payments, PARSERS["bank"](samples["bank"])


def test_demo_dataset_plants_exactly_three_payout_problems():
    _, payments, bank_lines = _demo()
    r = reconcile_payouts(payments, bank_lines)
    s = r["summary"]
    assert s["payouts_missing"] == 1 and s["payouts_short"] == 1 and s["bank_unexplained"] == 0
    assert s["payouts_landed"] + s["payouts_short"] + s["payouts_missing"] == s["payouts_expected"]
    assert any(p.get("combined_with") for p in r["payouts"])
    short = next(p for p in r["payouts"] if p["status"] == "short")
    assert short["source"] == "square" and short["delta"] == -45.0
    missing = next(p for p in r["payouts"] if p["status"] == "missing")
    assert missing["source"] == "stripe"
    assert s["cash_gap"] == round(missing["net"] + 45.0, 2)


def test_order_level_demo_numbers_are_unchanged():
    orders, payments, _ = _demo()
    s = reconcile(orders, payments)["summary"]
    assert s["match_rate"] == 95.8 and s["total_at_risk"] == 764.84 and s["exceptions"] == 5


def test_api_demo_report_merges_payout_exceptions_into_the_summary():
    from app import load_demo

    report = load_demo()
    assert report["summary"]["exceptions"] == len(report["exceptions"]) == 7
    assert report["summary"]["cash_gap"] == 674.06 and report["summary"]["total_at_risk"] == 764.84
    assert [f["source"] for f in report["files"]] == ["orders", "stripe", "square", "paypal", "bank"]
    assert report["exceptions"][0]["type"] == "payout_missing"  # biggest high-severity item leads
