# LedgerMatch

**Open-source payment reconciliation for small businesses.**

Your Stripe payout is one lump sum. It matches 50 different orders. The fees are buried. Square and PayPal do the same thing, differently. QuickBooks bank feeds don't help — so every month you (or your bookkeeper) burn 2–10 hours in a spreadsheet finding out whether the money actually arrived.

The SaaS answers (Synder, Webgility, A2X) cost $30–70/month and force you into their accounting suite.

LedgerMatch is the free, self-hosted answer:

**Drop your order export + your Stripe / Square / PayPal exports → get a matched ledger, a fee breakdown, and a red list of money that never arrived. In seconds. On your own machine.**

## What it catches

- **Missing payments** — orders with no payment in any processor export (money never arrived)
- **Orphan payments** — payments with no order behind them (unrecorded revenue)
- **Amount mismatches** — partial captures, wrong amounts, currency drift
- **Unlinked refunds** — refunds that can't be tied to any matched order
- **Fees** — totaled per processor, so you see what Stripe/Square/PayPal actually took

## How matching works

Three passes, highest confidence first:

1. **By reference** — the payment carries your order id (Stripe description, PayPal invoice number, Square note)
2. **Exact** — same amount, date within ±3 days
3. **Fuzzy** — amount within $0.02 (rounding drift), date within ±3 days

Everything unmatched becomes an exception, sorted by severity and dollar amount.

## Quickstart

Backend (Python 3.11+, FastAPI):

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --port 8000
```

Frontend (Next.js):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 and either click **Load demo data** (48 sample orders across 3 processors, with planted discrepancies) or drop your own CSVs.

## CSV formats

Parsers resolve columns by header name, not position, so standard exports work as-is:

| Source | Export | Key columns picked up |
|---|---|---|
| Orders | Shopify / any store export | Order ID, Date, Total, Customer |
| Stripe | Payments export | id, Created (UTC), Amount, Fee, Description |
| Square | Transactions CSV | Transaction ID, Date, Gross Sales, Fees |
| PayPal | Activity download | Transaction ID, Date, Gross, Fee, Invoice Number |

Source is auto-detected from filename or headers; ambiguous files can be tagged explicitly via the `source` form field.

## Privacy

Everything runs on localhost. No accounts, no telemetry, no upload to anyone's cloud. Your transaction data never leaves your machine.

## Roadmap

- Payout-level reconciliation (payout lump sum ↔ bank statement line)
- QuickBooks/Xero journal export of the matched ledger
- More processors (Razorpay, Adyen, Klarna)
- Scheduled runs + email digest of new exceptions

PRs welcome.

## License

MIT
