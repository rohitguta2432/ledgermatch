"use client";

import { useCallback, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Order = {
  order_id: string;
  date: string;
  amount: number;
  currency: string;
  customer: string;
};

type Payment = {
  id: string;
  source: string;
  date: string;
  gross: number;
  fee: number;
  net: number;
  currency: string;
  ref: string;
  description: string;
  kind: string;
};

type Match = {
  order: Order;
  payment: Payment;
  confidence: "ref" | "exact" | "fuzzy";
  delta: number;
  refunds?: Payment[];
};

type Exception = {
  type: string;
  severity: "high" | "medium" | "low";
  title: string;
  detail: string;
  amount: number;
};

type Payout = {
  id: string;
  source: string;
  date: string;
  charges: number;
  refunds: number;
  gross: number;
  fees: number;
  refunded: number;
  net: number;
  status: "expected" | "nothing_due" | "landed" | "short" | "over" | "missing";
  bank: { id: string; date: string; description: string; amount: number } | null;
  delta: number;
  combined_with?: string[];
};

type Report = {
  summary: {
    orders_total: number;
    payments_total: number;
    refunds_total: number;
    matched: number;
    match_rate: number;
    exceptions: number;
    total_fees: number;
    fees_by_source: Record<string, number>;
    gross_by_source: Record<string, number>;
    total_at_risk: number;
    payouts_expected?: number;
    payouts_landed?: number;
    payouts_short?: number;
    payouts_missing?: number;
    bank_credits?: number;
    bank_unexplained?: number;
    cash_gap?: number;
  };
  matches: Match[];
  exceptions: Exception[];
  payouts?: Payout[];
  files: { filename: string; source: string; rows: number }[];
};

const SOURCE_STYLES: Record<string, string> = {
  stripe: "bg-indigo-50 text-indigo-700 border-indigo-200",
  square: "bg-slate-100 text-slate-700 border-slate-300",
  paypal: "bg-sky-50 text-sky-700 border-sky-200",
  orders: "bg-amber-50 text-amber-700 border-amber-200",
  bank: "bg-emerald-50 text-emerald-700 border-emerald-200",
};

const EXCEPTION_LABELS: Record<string, string> = {
  missing_payment: "Missing payment",
  orphan_payment: "Orphan payment",
  amount_mismatch: "Amount mismatch",
  unlinked_refund: "Unlinked refund",
  payout_missing: "Payout never arrived",
  payout_short: "Payout landed short",
  payout_over: "Payout landed over",
  unexplained_deposit: "Unexplained deposit",
};

const PAYOUT_STATUS: Record<Payout["status"], { label: string; cls: string }> = {
  landed: { label: "landed ✓", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  short: { label: "landed short", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  over: { label: "landed over", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  missing: { label: "never arrived", cls: "bg-red-50 text-red-700 border-red-200" },
  expected: { label: "expected", cls: "bg-slate-100 text-slate-600 border-slate-200" },
  nothing_due: { label: "nothing due", cls: "bg-slate-100 text-slate-500 border-slate-200" },
};

function money(n: number) {
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
  });
}

export default function Home() {
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const loadDemo = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/api/demo`, { method: "POST" });
      if (!res.ok) throw new Error(`API returned ${res.status}`);
      setReport(await res.json());
    } catch (e) {
      setError(
        e instanceof Error && e.message.includes("fetch")
          ? "Backend not reachable. Start it with: uvicorn app:app --port 8000"
          : String(e),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const uploadFiles = useCallback(async (files: FileList | File[]) => {
    setLoading(true);
    setError(null);
    try {
      let last: Report | null = null;
      for (const file of Array.from(files)) {
        const body = new FormData();
        body.append("file", file);
        const res = await fetch(`${API}/api/upload`, { method: "POST", body });
        if (!res.ok) {
          const detail = await res.json().catch(() => null);
          throw new Error(detail?.detail ?? `Upload failed (${res.status})`);
        }
        last = await res.json();
      }
      if (last) setReport(last);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const reset = useCallback(async () => {
    await fetch(`${API}/api/reset`, { method: "POST" }).catch(() => null);
    setReport(null);
    setError(null);
  }, []);

  const summary = report?.summary;
  const hasData = !!summary && (summary.orders_total > 0 || summary.payments_total > 0);
  const payouts = (report?.payouts ?? []).filter((p) => p.status !== "nothing_due");
  const hasPayouts = payouts.length > 0;

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-600 font-bold text-white">
              L
            </div>
            <div>
              <span className="text-lg font-semibold tracking-tight">LedgerMatch</span>
              <span className="ml-3 hidden text-sm text-slate-500 sm:inline">
                open-source payment reconciliation
              </span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {hasData && (
              <button
                onClick={reset}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50"
              >
                Reset
              </button>
            )}
            <a
              href="https://github.com/rohitguta2432/ledgermatch"
              className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
            >
              GitHub ★
            </a>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        {!hasData && (
          <section className="mx-auto max-w-2xl pt-10 text-center">
            <h1 className="text-4xl font-bold tracking-tight text-slate-900">
              Your payouts are lump sums.
              <br />
              <span className="text-emerald-600">Your orders are not.</span>
            </h1>
            <p className="mx-auto mt-4 max-w-xl text-lg text-slate-600">
              Drop your Stripe, Square and PayPal exports next to your order list, plus your bank
              statement. LedgerMatch matches every order to its payment, rebuilds every payout, and
              shows you exactly which money never reached the bank.
            </p>

            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
              }}
              onClick={() => fileInput.current?.click()}
              className={`mt-10 cursor-pointer rounded-2xl border-2 border-dashed bg-white p-12 transition-colors ${
                dragOver ? "border-emerald-500 bg-emerald-50" : "border-slate-300 hover:border-slate-400"
              }`}
            >
              <input
                ref={fileInput}
                type="file"
                accept=".csv"
                multiple
                className="hidden"
                onChange={(e) => e.target.files && uploadFiles(e.target.files)}
              />
              <p className="text-lg font-medium text-slate-700">
                Drop CSVs here — orders + Stripe / Square / PayPal + your bank statement
              </p>
              <p className="mt-1 text-sm text-slate-500">
                Files never leave your machine. The backend runs on localhost.
              </p>
            </div>

            <div className="mt-6 flex items-center justify-center gap-4">
              <button
                onClick={loadDemo}
                disabled={loading}
                className="rounded-xl bg-emerald-600 px-6 py-3 text-base font-semibold text-white shadow-sm hover:bg-emerald-500 disabled:opacity-50"
              >
                {loading ? "Reconciling…" : "Load demo data"}
              </button>
              <span className="text-sm text-slate-500">48 orders · 3 processors · 1 bank statement · 1 click</span>
            </div>

            {error && (
              <p className="mt-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </p>
            )}
          </section>
        )}

        {hasData && summary && report && (
          <>
            <section className={`grid grid-cols-2 gap-4 ${hasPayouts ? "lg:grid-cols-5" : "lg:grid-cols-4"}`}>
              <StatCard
                label="Match rate"
                value={`${summary.match_rate}%`}
                sub={`${summary.matched} of ${summary.orders_total} orders`}
                tone="emerald"
              />
              <StatCard
                label="Money at risk"
                value={money(summary.total_at_risk)}
                sub={`${summary.exceptions} exceptions to review`}
                tone={summary.total_at_risk > 0 ? "red" : "emerald"}
              />
              {hasPayouts && (
                <StatCard
                  label="Cash gap"
                  value={money(summary.cash_gap ?? 0)}
                  sub={`${summary.payouts_landed} of ${summary.payouts_expected} payouts landed in the bank`}
                  tone={(summary.cash_gap ?? 0) > 0 ? "red" : "emerald"}
                />
              )}
              <StatCard
                label="Processor fees"
                value={money(summary.total_fees)}
                sub={Object.entries(summary.fees_by_source)
                  .map(([s, v]) => `${s} ${money(v)}`)
                  .join(" · ")}
                tone="slate"
              />
              <StatCard
                label="Gross processed"
                value={money(
                  Object.values(summary.gross_by_source).reduce((a, b) => a + b, 0),
                )}
                sub={`${summary.payments_total} payments · ${summary.refunds_total} refunds`}
                tone="slate"
              />
            </section>

            {report.exceptions.length > 0 && (
              <section className="mt-8">
                <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-red-100 text-sm font-bold text-red-600">
                    {report.exceptions.length}
                  </span>
                  Exceptions — review these
                </h2>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  {report.exceptions.map((exc, i) => (
                    <div
                      key={i}
                      className={`rounded-xl border p-4 ${
                        exc.severity === "high"
                          ? "border-red-200 bg-red-50"
                          : "border-amber-200 bg-amber-50"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <span
                            className={`text-xs font-semibold uppercase tracking-wide ${
                              exc.severity === "high" ? "text-red-600" : "text-amber-700"
                            }`}
                          >
                            {EXCEPTION_LABELS[exc.type] ?? exc.type}
                          </span>
                          <p className="mt-1 font-medium text-slate-900">{exc.title}</p>
                          <p className="mt-1 text-sm text-slate-600">{exc.detail}</p>
                        </div>
                        <span
                          className={`whitespace-nowrap text-lg font-bold ${
                            exc.severity === "high" ? "text-red-600" : "text-amber-700"
                          }`}
                        >
                          {money(exc.amount)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {hasPayouts && (
              <section className="mt-8">
                <h2 className="text-lg font-semibold text-slate-900">
                  Payouts → bank
                  <span className="ml-2 text-sm font-normal text-slate-500">
                    every processor payout, rebuilt from its charges and checked against your statement
                  </span>
                </h2>
                <div className="mt-3 overflow-x-auto rounded-xl border border-slate-200 bg-white">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                        <th className="px-4 py-3">Processor</th>
                        <th className="px-4 py-3">Settles</th>
                        <th className="px-4 py-3 text-right">Charges</th>
                        <th className="px-4 py-3 text-right">Gross</th>
                        <th className="px-4 py-3 text-right">Fees</th>
                        <th className="px-4 py-3 text-right">Net expected</th>
                        <th className="px-4 py-3">Bank statement</th>
                        <th className="px-4 py-3">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {payouts.map((p) => (
                        <tr
                          key={p.id}
                          className={`border-b border-slate-100 last:border-0 ${
                            p.status === "missing" ? "bg-red-50/60" : p.status === "short" ? "bg-amber-50/60" : "hover:bg-slate-50"
                          }`}
                        >
                          <td className="px-4 py-2.5">
                            <span
                              className={`rounded-md border px-2 py-0.5 text-xs font-medium ${
                                SOURCE_STYLES[p.source] ?? SOURCE_STYLES.orders
                              }`}
                            >
                              {p.source}
                            </span>
                          </td>
                          <td className="px-4 py-2.5 text-slate-600">{p.date}</td>
                          <td className="px-4 py-2.5 text-right text-slate-600">
                            {p.charges}
                            {p.refunds ? ` − ${p.refunds} refund` : ""}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono">{money(p.gross)}</td>
                          <td className="px-4 py-2.5 text-right font-mono text-slate-500">−{money(p.fees)}</td>
                          <td className="px-4 py-2.5 text-right font-mono font-medium">{money(p.net)}</td>
                          <td className="px-4 py-2.5 text-slate-600">
                            {p.bank ? (
                              <>
                                <span className="font-mono">{money(p.bank.amount)}</span>
                                <span className="ml-2 text-xs text-slate-400">
                                  {p.bank.date} · {p.bank.description}
                                  {p.combined_with?.length ? " · combined transfer" : ""}
                                </span>
                              </>
                            ) : (
                              <span className="text-slate-400">—</span>
                            )}
                          </td>
                          <td className="px-4 py-2.5">
                            <span
                              className={`whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium ${
                                PAYOUT_STATUS[p.status].cls
                              }`}
                            >
                              {PAYOUT_STATUS[p.status].label}
                              {p.status === "short" ? ` ${money(p.delta)}` : ""}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            <section className="mt-8">
              <h2 className="text-lg font-semibold text-slate-900">
                Matched ledger
                <span className="ml-2 text-sm font-normal text-slate-500">
                  {report.matches.length} orders matched to payments
                </span>
              </h2>
              <div className="mt-3 overflow-x-auto rounded-xl border border-slate-200 bg-white">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                      <th className="px-4 py-3">Order</th>
                      <th className="px-4 py-3">Customer</th>
                      <th className="px-4 py-3">Date</th>
                      <th className="px-4 py-3">Source</th>
                      <th className="px-4 py-3 text-right">Gross</th>
                      <th className="px-4 py-3 text-right">Fee</th>
                      <th className="px-4 py-3 text-right">Net</th>
                      <th className="px-4 py-3">Match</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.matches.map((m) => (
                      <tr
                        key={`${m.payment.source}-${m.payment.id}`}
                        className="border-b border-slate-100 last:border-0 hover:bg-slate-50"
                      >
                        <td className="px-4 py-2.5 font-medium">#{m.order.order_id}</td>
                        <td className="px-4 py-2.5 text-slate-600">{m.order.customer}</td>
                        <td className="px-4 py-2.5 text-slate-600">{m.payment.date}</td>
                        <td className="px-4 py-2.5">
                          <span
                            className={`rounded-md border px-2 py-0.5 text-xs font-medium ${
                              SOURCE_STYLES[m.payment.source] ?? SOURCE_STYLES.orders
                            }`}
                          >
                            {m.payment.source}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono">{money(m.payment.gross)}</td>
                        <td className="px-4 py-2.5 text-right font-mono text-slate-500">
                          −{money(m.payment.fee)}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono font-medium">
                          {money(m.payment.net)}
                        </td>
                        <td className="px-4 py-2.5">
                          <span
                            className={`text-xs font-medium ${
                              m.confidence === "ref"
                                ? "text-emerald-600"
                                : m.confidence === "exact"
                                  ? "text-emerald-500"
                                  : "text-amber-600"
                            }`}
                          >
                            {m.confidence === "ref"
                              ? "● by reference"
                              : m.confidence === "exact"
                                ? "● exact amount"
                                : "◐ fuzzy"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <p className="mt-8 text-center text-xs text-slate-400">
              Loaded: {report.files.map((f) => `${f.filename} (${f.rows} rows)`).join(" · ")}
            </p>
          </>
        )}
      </main>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub: string;
  tone: "emerald" | "red" | "slate";
}) {
  const valueColor =
    tone === "emerald" ? "text-emerald-600" : tone === "red" ? "text-red-600" : "text-slate-900";
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1.5 text-3xl font-bold tracking-tight ${valueColor}`}>{value}</p>
      <p className="mt-1 truncate text-xs text-slate-500" title={sub}>
        {sub}
      </p>
    </div>
  );
}
