"""LedgerMatch API — reconcile store orders against processor payouts."""

from __future__ import annotations

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

import sample_data
from matcher import reconcile
from normalize import PARSERS, detect_source

app = FastAPI(title="LedgerMatch", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single-workspace in-memory state (v0.1 — one merchant, one session)
STATE: dict = {"orders": [], "payments": [], "files": []}


def _current_report() -> dict:
    report = reconcile(STATE["orders"], STATE["payments"])
    report["files"] = STATE["files"]
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
            detail="Could not detect the source. Pass source=stripe|square|paypal|orders.",
        )
    parsed = PARSERS[resolved](text)
    if resolved == "orders":
        STATE["orders"] = [o for o in STATE["orders"] if True] + parsed
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
    STATE["orders"] = []
    STATE["payments"] = []
    STATE["files"] = []
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
    return _current_report()


@app.get("/api/report")
def report() -> dict:
    return _current_report()


@app.post("/api/reset")
def reset() -> dict:
    STATE["orders"] = []
    STATE["payments"] = []
    STATE["files"] = []
    return {"ok": True}
