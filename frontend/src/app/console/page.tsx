"use client";

// Replays a recorded engine run (public/demo/events.jsonl) as a live console.
// The engine finishes in a few milliseconds, so events are replayed at a
// fixed cadence and the chip says so. Every line is a real event the engine
// emitted, in order, with its real timestamp — nothing here is synthesized.
// Regenerate the file with: backend/.venv/bin/python run_demo.py public/demo/events.jsonl

import { useEffect, useMemo, useRef, useState } from "react";

interface Ev {
  t: number;
  kind: string;
  files?: string[];
  file?: string;
  source?: string;
  rows?: number;
  name?: string;
  matched?: number;
  orders?: number;
  exceptions?: number;
  at_risk?: number;
  payments?: number;
  date?: string;
  dates?: string[];
  nets?: number[];
  charges?: number;
  refunds?: number;
  gross?: number;
  fees?: number;
  net?: number;
  lines?: number;
  credits?: number;
  processor_credits?: number;
  bank_id?: string;
  bank_date?: string;
  description?: string;
  amount?: number;
  delta?: number;
  payouts_expected?: number;
  payouts_landed?: number;
  payouts_short?: number;
  payouts_missing?: number;
  bank_credits?: number;
  bank_unexplained?: number;
  cash_gap?: number;
}

const SETTLE_MS = 900; // idle beat before the first line
const FIT_MS = 12300; // the run is spread over this much of the 15 s clip
const MAX_LINES = 22;

const usd = (n: number | undefined) =>
  (n ?? 0).toLocaleString("en-US", { style: "currency", currency: "USD" });
const md = (iso: string | undefined) => (iso ?? "").slice(5); // MM-DD
const SRC: Record<string, string> = { stripe: "Stripe", square: "Square", paypal: "PayPal" };

function line(e: Ev): { cls: string; kw: string; body: React.ReactNode } | null {
  switch (e.kind) {
    case "run_start":
      return { cls: "head", kw: "run", body: <>{e.files?.join(" · ")}</> };
    case "load":
      return { cls: "", kw: "load", body: <>{e.file} · {e.rows} rows</> };
    case "pass":
      return {
        cls: "",
        kw: "match",
        body: (
          <>
            pass <span className="q">{e.name}</span> · {e.matched} orders matched so far
          </>
        ),
      };
    case "orders_done":
      return {
        cls: "head",
        kw: "orders",
        body: (
          <>
            {e.matched}/{e.orders} matched · {e.exceptions} exceptions · {usd(e.at_risk)} at risk
          </>
        ),
      };
    case "payouts_start":
      return { cls: "head", kw: "payouts", body: <>rebuilding payouts from {e.payments} charges and refunds</> };
    case "payout":
      return {
        cls: "",
        kw: "payout",
        body: (
          <>
            <span className="q">{SRC[e.source ?? ""]}</span> {md(e.date)} · {e.charges} charge{e.charges === 1 ? "" : "s"}
            {e.refunds ? ` · ${e.refunds} refund` : ""} · gross {usd(e.gross)} − fees {usd(e.fees)}
            <span className="arr">=</span>
            {usd(e.net)}
          </>
        ),
      };
    case "bank":
      return {
        cls: "head",
        kw: "bank",
        body: <>{e.lines} statement lines · {e.credits} credits · {e.processor_credits} from processors</>,
      };
    case "landed":
      return {
        cls: "okay",
        kw: "landed",
        body: (
          <>
            <span className="q">{SRC[e.source ?? ""]}</span> {md(e.date)} {usd(e.net)}
            <span className="arr">→</span>
            {e.description} ✓
          </>
        ),
      };
    case "combined":
      return {
        cls: "okay",
        kw: "combined",
        body: (
          <>
            <span className="q">{SRC[e.source ?? ""]}</span> {e.dates?.map(md).join(" + ")}
            <span className="arr">→</span>
            one transfer of {usd(e.amount)} ✓
          </>
        ),
      };
    case "short":
      return {
        cls: "warn",
        kw: "short",
        body: (
          <>
            <span className="q">{SRC[e.source ?? ""]}</span> {md(e.date)} expected {usd(e.net)} · bank shows {usd(e.amount)}
            <span className="arr">→</span>
            {usd(-(e.delta ?? 0))} held back
          </>
        ),
      };
    case "over":
      return { cls: "warn", kw: "over", body: <>{SRC[e.source ?? ""]} {md(e.date)} landed over by {usd(e.delta)}</> };
    case "missing":
      return {
        cls: "fail",
        kw: "MISSING",
        body: (
          <>
            <span className="q">{SRC[e.source ?? ""]}</span> {md(e.date)} {usd(e.net)} · {e.charges} charges
            <span className="arr">→</span>
            no bank credit within ±3 days
          </>
        ),
      };
    case "unexplained":
      return { cls: "warn", kw: "unknown", body: <>{e.description} {usd(e.amount)} — no payout behind it</> };
    case "run_end":
      return {
        cls: "head",
        kw: "done",
        body: (
          <>
            {e.payouts_landed}/{e.payouts_expected} landed · {e.payouts_short} short · {e.payouts_missing} missing ·
            cash gap {usd(e.cash_gap)}
          </>
        ),
      };
    default:
      return null;
  }
}

export default function Console() {
  const [events, setEvents] = useState<Ev[]>([]);
  const [idx, setIdx] = useState(0);
  const t0 = useRef<number | null>(null);

  useEffect(() => {
    fetch("/demo/events.jsonl")
      .then((r) => r.text())
      .then((text) => setEvents(text.split("\n").filter(Boolean).map((l) => JSON.parse(l) as Ev)));
  }, []);

  const stepMs = useMemo(() => (events.length ? FIT_MS / events.length : 1), [events]);

  // ?t=<ms into the visual timeline> renders that instant and does not animate.
  // The frame recorder steps this param, so capture speed cannot skew playback.
  const fixedT = useMemo(() => {
    if (typeof window === "undefined") return null;
    const v = new URLSearchParams(window.location.search).get("t");
    return v === null ? null : Number(v);
  }, []);

  const idxAt = (visualMs: number) =>
    Math.min(events.length, Math.floor(Math.max(0, visualMs - SETTLE_MS) / stepMs));

  useEffect(() => {
    if (!events.length) return;
    (window as unknown as { __setT?: (ms: number) => void }).__setT = (ms) => setIdx(idxAt(ms));
    if (fixedT !== null) {
      setIdx(idxAt(fixedT));
      return;
    }
    const iv = setInterval(() => {
      if (t0.current === null) t0.current = performance.now();
      const i = idxAt(performance.now() - t0.current);
      setIdx(i);
      if (i >= events.length) clearInterval(iv);
    }, 40);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events, stepMs, fixedT]);

  const seen = events.slice(0, idx);
  const realMs = events.length ? events[events.length - 1].t : 0;

  // Payout board: one chip per expected payout, lit by the bank pass.
  const board = useMemo(() => {
    const chips: { id: string; source: string; date: string; net: number; status: string; delta: number }[] = [];
    const byId = new Map<string, (typeof chips)[number]>();
    for (const e of seen) {
      if (e.kind === "payout") {
        const chip = {
          id: `${e.source}-${e.date}`,
          source: e.source ?? "",
          date: e.date ?? "",
          net: e.net ?? 0,
          status: (e.net ?? 0) > 0.02 ? "expected" : "none",
          delta: 0,
        };
        chips.push(chip);
        byId.set(chip.id, chip);
      } else if (e.kind === "landed" || e.kind === "short" || e.kind === "over" || e.kind === "missing") {
        const chip = byId.get(`${e.source}-${e.date}`);
        if (chip) {
          chip.status = e.kind === "landed" ? "landed" : e.kind;
          chip.delta = e.delta ?? 0;
        }
      } else if (e.kind === "combined") {
        for (const d of e.dates ?? []) {
          const chip = byId.get(`${e.source}-${d}`);
          if (chip) chip.status = "landed";
        }
      }
    }
    return chips;
  }, [seen]);

  const counts = { expected: 0, landed: 0, short: 0, missing: 0 };
  let gap = 0;
  for (const c of board) {
    if (c.status === "none") continue;
    counts.expected++;
    if (c.status === "landed") counts.landed++;
    if (c.status === "short") {
      counts.short++;
      gap += -c.delta;
    }
    if (c.status === "missing") {
      counts.missing++;
      gap += c.net;
    }
  }
  const bank = seen.find((e) => e.kind === "bank");
  const explained = seen.filter((e) => e.kind === "landed" || e.kind === "combined" || e.kind === "short").length;
  const end = seen.find((e) => e.kind === "run_end");
  const missingEv = seen.find((e) => e.kind === "missing");
  const shortEv = seen.find((e) => e.kind === "short");

  const lines = seen
    .map((e) => ({ e, r: line(e) }))
    .filter((x): x is { e: Ev; r: NonNullable<ReturnType<typeof line>> } => x.r !== null)
    .slice(-MAX_LINES);

  return (
    <div className="con">
      <div className="con-top">
        <h1 className="brand">
          Ledger<span className="tick">Match</span>
        </h1>
        <span className="tag-line">orders → charges → payouts → your bank statement</span>
        <span className="chip mono">
          engine · <b>4 passes + payout ladder</b>
        </span>
        <span className="chip replay mono">
          recorded run · {realMs.toFixed(1)} ms real · replayed at 1 line / {Math.round(stepMs)} ms
        </span>
      </div>

      <div className="con-body">
        <div className="con-left">
          <div>
            <p className="panel-h">Payouts → bank</p>
            <div className="tiles">
              <div className={`tile ${counts.expected ? "" : "zero"}`}>
                <div className="k">Payouts expected</div>
                <div className="v">{counts.expected}</div>
              </div>
              <div className={`tile ok ${counts.landed ? "" : "zero"}`}>
                <div className="k">Landed in bank</div>
                <div className="v">{counts.landed}</div>
              </div>
              <div className={`tile bad ${gap ? "" : "zero"}`}>
                <div className="k">Cash gap</div>
                <div className="v">{usd(gap)}</div>
              </div>
              <div className={`tile ${bank ? "" : "zero"}`}>
                <div className="k">Credits explained</div>
                <div className="v">
                  {bank ? explained : 0}
                  <span className="of">/{bank?.processor_credits ?? 0}</span>
                </div>
              </div>
            </div>
          </div>
          <div className="board-wrap">
            <p className="panel-h">Payout board</p>
            <div className="board">
              {board.map((c) => (
                <div key={c.id} className={`pchip ${c.status}`} title={`${SRC[c.source]} ${c.date} ${usd(c.net)}`}>
                  <span className="src">{SRC[c.source]?.[0]}</span>
                  <span className="d mono">{md(c.date)}</span>
                  <span className="n mono">{c.status === "none" ? "—" : usd(c.net)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="con-main">
          <div className={`verdict ${end ? "show" : ""} ${end && (end.payouts_missing || end.payouts_short) ? "bad" : "ok"}`}>
            {end && (end.payouts_missing || end.payouts_short) ? (
              <>
                <span className="v-amt">{usd(end.cash_gap)}</span>
                <span className="v-txt">
                  never reached your bank.
                  {missingEv && ` ${SRC[missingEv.source ?? ""]} payout of ${usd(missingEv.net)} (${md(missingEv.date)}) is missing.`}
                  {shortEv && ` ${SRC[shortEv.source ?? ""]} landed ${usd(-(shortEv.delta ?? 0))} short.`}
                </span>
              </>
            ) : (
              <span className="v-txt">Every payout landed. The bank agrees with the processors.</span>
            )}
          </div>
          <div className="log">
            {lines.map(({ e, r }, i) => (
              <div key={`${e.t}-${i}`} className={`log-line ${r.cls}`}>
                <span className="t">{e.t.toFixed(2)}ms</span>
                <span className="kw">{r.kw}</span>
                {r.body}
              </div>
            ))}
          </div>
          <div className="con-foot">
            <span>reference → exact → fuzzy → payout ladder · runs on localhost, nothing leaves your machine</span>
            <span className="mono">github.com/rohitguta2432/ledgermatch</span>
          </div>
        </div>
      </div>
    </div>
  );
}
