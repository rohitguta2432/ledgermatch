"""LedgerMatch API — reconcile store orders against processor payments, and processor payouts against the bank."""

from __future__ import annotations

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

import sample_data
from matcher import reconcile
from normalize import PARSERS, detect_source
from payouts import EventLog, reconcile_payouts

app = FastAPI(title="LedgerMatch", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single-workspace in-memory state (one merchant, one session)
STATE: dict = {"orders": [], "payments": [], "bank": [], "files": [], "events": []}

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _clear() -> None:
    for key in ("orders", "payments", "bank", "files", "events"):
        STATE[key] = []


def _current_report() -> dict:
    log = EventLog()
    log("run_start", orders=len(STATE["orders"]), payments=len(STATE["payments"]),
        bank=len(STATE["bank"]), files=[f["filename"] for f in STATE["files"]])
    report = reconcile(STATE["orders"], STATE["payments"], emit=log)
    report["payouts"] = []
    if STATE["bank"]:
        payouts = reconcile_payouts(STATE["payments"], STATE["bank"], emit=log)
        report["payouts"] = payouts["payouts"]
        report["summary"].update(payouts["summary"])
        report["exceptions"] = sorted(
            report["exceptions"] + payouts["exceptions"],
            key=lambda e: (SEVERITY_RANK[e["severity"]], -e["amount"]),
        )
        report["summary"]["exceptions"] = len(report["exceptions"])
    report["files"] = STATE["files"]
    STATE["events"] = log.events
    return report


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), source: str = Form("")) -> dict:
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    resolved = source.lower().strip() or detect_source(file.filename or "", text)
    if resolved not in PARSERS:
        raise HTTPException(
            status_code=422,
            detail="Could not detect the source. Pass source=stripe|square|paypal|orders|bank.",
        )
    parsed = PARSERS[resolved](text)
    if resolved == "orders":
        STATE["orders"].extend(parsed)
    elif resolved == "bank":
        STATE["bank"].extend(parsed)
    else:
        STATE["payments"].extend(parsed)
    STATE["files"].append({
        "filename": file.filename,
        "source": resolved,
        "rows": len(parsed),
    })
    return _current_report()


@app.post("/api/demo")
def load_demo() -> dict:
    """Load the bundled sample dataset (used by the landing demo button)."""
    _clear()
    samples = sample_data.generate()
    STATE["orders"] = PARSERS["orders"](samples["orders"])
    for source in ("stripe", "square", "paypal"):
        STATE["payments"].extend(PARSERS[source](samples[source]))
        STATE["files"].append({
            "filename": f"{source}.csv",
            "source": source,
            "rows": len(samples[source].splitlines()) - 1,
        })
    STATE["files"].insert(0, {
        "filename": "orders.csv",
        "source": "orders",
        "rows": len(STATE["orders"]),
    })
    STATE["bank"] = PARSERS["bank"](samples["bank"])
    STATE["files"].append({"filename": "bank.csv", "source": "bank", "rows": len(STATE["bank"])})
    return _current_report()


@app.get("/api/report")
def report() -> dict:
    return _current_report()


@app.get("/api/events")
def events() -> list[dict]:
    """The last run, as the engine emitted it (millisecond timestamps). Feeds the console replay."""
    return STATE["events"]


@app.post("/api/reset")
def reset() -> dict:
    _clear()
    return {"ok": True}
