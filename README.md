# LedgerMatch

**Open-source payment reconciliation for small businesses.**

Your Stripe payout is one lump sum. It matches 50 different orders. The fees are buried. Square and PayPal do the same thing, differently. QuickBooks bank feeds don't help — so every month you (or your bookkeeper) burn 2–10 hours in a spreadsheet finding out whether the money actually arrived.

The SaaS answers (Synder, Webgility, A2X) cost $30–70/month and force you into their accounting suite.

LedgerMatch is the free, self-hosted answer:

**Drop your order export + your Stripe / Square / PayPal exports + your bank statement → get a matched ledger, a fee breakdown, every payout checked against the bank, and a red list of money that never arrived. In seconds. On your own machine.**

## What it catches

- **Missing payments** — orders with no payment in any processor export (money never arrived)
- **Orphan payments** — payments with no order behind them (unrecorded revenue)
- **Amount mismatches** — partial captures, wrong amounts, currency drift
- **Unlinked refunds** — refunds that can't be tied to any matched order
- **Fees** — totaled per processor, so you see what Stripe/Square/PayPal actually took
- **Payouts that never landed** — a processor payout with no matching bank credit (money stuck, or paid to the wrong account)
- **Payouts that landed short** — the bank shows less than the charges minus fees (reserve holds, chargebacks, fee changes)
- **Unexplained processor deposits** — a Stripe/Square/PayPal credit in the bank with no payout behind it

## How matching works

Three passes, highest confidence first:

1. **By reference** — the payment carries your order id (Stripe description, PayPal invoice number, Square note)
2. **Exact** — same amount, date within ±3 days
3. **Fuzzy** — amount within $0.02 (rounding drift), date within ±3 days

Everything unmatched becomes an exception, sorted by severity and dollar amount.

### Payouts → bank (v0.2)

Matching orders to charges proves the customer paid. The payout ladder proves the money reached you:

1. **Rebuild the payouts** — every charge and refund is grouped into the payout the processor should have sent, per processor and settlement day (Stripe settles in 2 days, Square in 1, PayPal same day). Net = gross − fees − refunds.
2. **Find each payout in the bank statement** — exact net amount within ±3 days first; then *combined* transfers where several consecutive payouts landed as one credit (subset-sum, up to 4 payouts); then *short* landings where the credit is 50–120% of the expected net.
3. **Flag the rest** — `payout_missing`, `payout_short`, `unexplained_deposit`. The **cash gap** on the dashboard is the sum of missing payouts and short deltas: money the processors say they sent that the bank never showed.

Bank lines are attributed to a processor by their description (`STRIPE TRANSFER`, `SQUARE INC`, `SQ *`, `PAYPAL TRANSFER`); untagged credits like `ACH CREDIT` can still land a payout on an exact amount.

## Quickstart

Backend tests: `cd backend && .venv/bin/pytest tests -q`

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

Open http://localhost:3000 and either click **Load demo data** (48 sample orders across 3 processors plus a bank statement, with planted discrepancies) or drop your own CSVs.

### The demo, recorded

`/console` replays a real engine run as a live console — the events file it reads was written by the engine, timestamped in milliseconds, nothing synthesized:

```bash
cd backend && .venv/bin/python run_demo.py ../frontend/public/demo/events.jsonl   # record a run
cd ../frontend && npm run record -- /tmp/frames http://localhost:3000             # frame-step /console with Playwright (Chrome)
ffmpeg -framerate 30 -i /tmp/frames/f%04d.png -vf scale=1600:900 -c:v libx264 -pix_fmt yuv420p -crf 18 clip.mp4
```

## CSV formats

Parsers resolve columns by header name, not position, so standard exports work as-is:

| Source | Export | Key columns picked up |
|---|---|---|
| Orders | Shopify / any store export | Order ID, Date, Total, Customer |
| Stripe | Payments export | id, Created (UTC), Amount, Fee, Description |
| Square | Transactions CSV | Transaction ID, Date, Gross Sales, Fees |
| PayPal | Activity download | Transaction ID, Date, Gross, Fee, Invoice Number |
| Bank | Any statement CSV | Date, Description, Amount (or Credit / Debit), Balance |

Source is auto-detected from filename or headers; ambiguous files can be tagged explicitly via the `source` form field.

## Privacy

Everything runs on localhost. No accounts, no telemetry, no upload to anyone's cloud. Your transaction data never leaves your machine.

## Roadmap

- ~~Payout-level reconciliation (payout lump sum ↔ bank statement line)~~ shipped in v0.2
- Processor payout exports (Stripe payouts.csv) as the payout source of truth instead of rebuilding from charges
- QuickBooks/Xero journal export of the matched ledger
- More processors (Razorpay, Adyen, Klarna)
- Scheduled runs + email digest of new exceptions

PRs welcome.

## License

MIT

---

### 🤝 Work with me

I'm an **AI Consultant · Forward Deployed Engineer** — I embed with teams and ship AI to production: agents, MCP integrations, and LLM features, with evals proving they work.

**→ [rohitraj.tech/en/hire](https://rohitraj.tech/en/hire)**
