"""csa-extension: the MCP server we built. Run standalone:  python -m csa.mcp_server

Read tools  : list_households, get_household_plot, get_rainfall_signal, get_pest_alerts, get_market_prices
Write tools : draft_advisory, file_flag, schedule_followup
Write tools only create PENDING_APPROVAL rows. There is deliberately NO tool that sends, orders or
raises a credit flag for real - that code lives in csa/dispatcher.py behind the human approval gate.
Every call (inputs, outputs, error, duration) is appended to the hash-chained audit log."""
import functools, os, statistics, time
from datetime import date, timedelta
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from csa import audit, data, store

RUN_ID = os.environ.get("CSA_RUN_ID", "adhoc")
SERVED: set[str] = set()       # source ids this server has actually returned in this run
mcp = MCPServer("csa-extension", instructions="Climate-smart advisory tools for an extension office. "
    "Cite only source_ids returned by read tools. Write tools create drafts that a named officer must approve.")
READ = ToolAnnotations(readOnlyHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False)

def logged(fn):
    @functools.wraps(fn)
    def w(*a, **k):
        t0 = time.time()
        try:
            out = fn(*a, **k); err = None
        except Exception as e:  # tools never crash the session; the agent sees a structured error
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"}; err = str(e)
        audit.append(RUN_ID, "agent", "tool_call", server="csa-extension", tool=fn.__name__, inputs=k,
                     outputs=out, error=err, ms=round((time.time() - t0) * 1000, 1))
        return out
    return w

def serve(*ids): SERVED.update(i for i in ids if i)

@mcp.tool(annotations=READ)
@logged
def list_households(collective_id: str) -> dict:
    """List household ids in one collective (e.g. KAV-A, MUT-B, NDU-C)."""
    hh = [r for r in data.rows("households.csv") if r["collective_id"] == collective_id]
    if not hh: return {"ok": False, "error": f"unknown collective {collective_id}"}
    return {"ok": True, "collective_id": collective_id, "households": [{"household_id": r["household_id"], "ward": r["ward"]} for r in hh]}

@mcp.tool(annotations=READ)
@logged
def get_household_plot(household_id: str) -> dict:
    """Plot record for one household with a data_quality list describing missing or inconsistent fields."""
    r = data.household(household_id)
    if not r: return {"ok": False, "error": f"unknown household {household_id}"}
    n = data.normalise_household(r); serve(n["source_id"]); return {"ok": True, **n}

@mcp.tool(annotations=READ)
@logged
def get_rainfall_signal(station_id: str | None, zone_id: str, ward: str | None = None) -> dict:
    """Dekadal rainfall for a station, an onset assessment (MET / NOT_MET / INDETERMINATE) with the rule shown,
    and the seasonal outlook for the zone. If the station has no data, returns status no_station plus the
    nearest station so the caller can retry with a clearly-labelled proxy."""
    st = data.jload("stations.json"); outlook = st["outlooks"].get(zone_id)
    if outlook: serve(outlook["source_id"])
    if not station_id or station_id not in st["stations"]:
        fb = st["nearest_station"].get(ward or "")
        return {"ok": True, "status": "no_station", "station_id": station_id, "fallback": fb, "outlook": outlook,
                "note": "No rainfall data for this station. Retry with fallback station as a PROXY and lower confidence."}
    rec = [r for r in data.rows("rainfall.csv") if r["station_id"] == station_id]
    rec.sort(key=lambda r: r["dekad_start"])
    dek = [{"source_id": f"RF-{station_id}-{r['dekad_start']}", "dekad_start": r["dekad_start"],
            "mm": float(r["mm"]) if r["mm"] != "" else None, "provisional": r["provisional"] == "yes"} for r in rec]
    serve(*[d["source_id"] for d in dek])
    last3 = dek[-3:]
    rule = "Onset = MET when the last two complete dekads total >= 40 mm. INDETERMINATE if any of the last three dekads is missing."
    if any(d["mm"] is None for d in last3):
        status = "INDETERMINATE"; missing = [d["dekad_start"] for d in last3 if d["mm"] is None]
    else:
        status = "MET" if sum(d["mm"] for d in last3[-2:]) >= 40 else "NOT_MET"; missing = []
    return {"ok": True, "station_id": station_id, "dekads": dek, "onset_status": status, "rule": rule,
            "two_dekad_total_mm": None if status == "INDETERMINATE" else sum(d["mm"] for d in last3[-2:]),
            "missing_dekads": missing, "latest_is_provisional": dek[-1]["provisional"], "outlook": outlook}

@mcp.tool(annotations=READ)
@logged
def get_pest_alerts(ward: str, max_age_days: int = 21) -> dict:
    """Pest alerts for a ward. Alerts older than max_age_days are returned separately as stale and must not drive advice."""
    today = data.as_of(); fresh, stale = [], []
    for a in data.jload("pest_alerts.json"):
        if a["ward"] != ward: continue
        age = (today - date.fromisoformat(a["reported"])).days
        (fresh if age <= max_age_days else stale).append({**a, "source_id": a["alert_id"], "age_days": age})
    serve(*[a["source_id"] for a in fresh + stale])
    return {"ok": True, "ward": ward, "as_of": today.isoformat(), "fresh": fresh, "stale_excluded": stale}

@mcp.tool(annotations=READ)
@logged
def get_market_prices(crop: str) -> dict:
    """Weekly prices (KES per 90kg) by aggregation centre, with outliers removed and a 4-week trend on clean data."""
    rows = [r for r in data.rows("prices.csv") if r["crop"] == crop]
    if not rows: return {"ok": False, "error": f"no prices for {crop}"}
    weeks = sorted({r["week"] for r in rows}); by_wk = {w: [r for r in rows if r["week"] == w] for w in weeks}
    outliers, clean = [], []
    for w in weeks:
        med = statistics.median(float(r["price_kes_per_90kg"]) for r in by_wk[w])
        for r in by_wk[w]:
            p = float(r["price_kes_per_90kg"]); sid = f"PR-{r['market_id']}-{crop}-{w}"; serve(sid)
            rec = {"source_id": sid, "market_id": r["market_id"], "week": w, "price": p}
            if len(by_wk[w]) >= 3 and (p > 1.6 * med or p < 0.6 * med): outliers.append({**rec, "reason": f"{p/med:.1f}x the week's median"})
            else: clean.append(rec)
    latest = max(weeks); mk = {}
    for r in clean: mk.setdefault(r["market_id"], []).append(r)
    summary = []
    for m, s in mk.items():
        s.sort(key=lambda x: x["week"]); first, last = s[0], s[-1]
        summary.append({"market_id": m, "latest_week": last["week"], "latest_price": last["price"], "latest_source_id": last["source_id"],
                        "first_source_id": first["source_id"], "trend_pct": round(100 * (last["price"] - first["price"]) / first["price"], 1) if len(s) > 1 else None})
    best = max((s for s in summary if s["latest_week"] == latest), key=lambda s: s["latest_price"], default=None)
    return {"ok": True, "crop": crop, "latest_week": latest, "markets": summary, "outliers_excluded": outliers, "best_clean_market": best}

REC = {"PLANT", "WAIT", "SPRAY", "HOLD", "SELL", "REVIEW"}
FLAGS = {"input_order_request", "credit_flag", "pest_followup_visit", "record_review"}

def _check_cites(cites):
    if not cites: return "citations required: an unsourced recommendation is not accepted"
    bad = [c for c in cites if c not in SERVED]
    return f"unknown or never-retrieved source ids: {bad}. Cite only source_id values returned by read tools" if bad else None

def _pending_exists(hid, kind):
    return any(a["household_id"] == hid and a["kind"] == kind and a["status"] in ("PENDING_APPROVAL", "APPROVED", "EXECUTED")
               for a in store.listing(run_id=RUN_ID))

@mcp.tool(annotations=WRITE)
@logged
def draft_advisory(household_id: str, recommendation: str, crop: str, sms_text: str, officer_brief: str,
                   citations: list[str], confidence: str, caveats: list[str], channel: str) -> dict:
    """Draft (never send) an advisory for one household. Stored as PENDING_APPROVAL; a named officer must approve it.
    recommendation: PLANT|WAIT|SPRAY|HOLD|SELL|REVIEW. confidence: high|medium|low. channel: sms|ussd|home_visit.
    Every id in citations must have been returned by a read tool in this run."""
    r = data.household(household_id)
    if not r: return {"ok": False, "error": f"unknown household {household_id}"}
    if recommendation not in REC: return {"ok": False, "error": f"recommendation must be one of {sorted(REC)}"}
    if confidence not in ("high", "medium", "low"): return {"ok": False, "error": "confidence must be high|medium|low"}
    if channel not in ("sms", "ussd", "home_visit"): return {"ok": False, "error": "channel must be sms|ussd|home_visit"}
    if not (1 <= len(sms_text) <= 320): return {"ok": False, "error": "sms_text must be 1-320 characters"}
    if (e := _check_cites(citations)): return {"ok": False, "error": e}
    if _pending_exists(household_id, "advisory"): return {"ok": False, "error": f"an advisory for {household_id} already exists in this run"}
    aid = store.create(RUN_ID, "advisory", household_id, r["collective_id"], dict(
        recommendation=recommendation, crop=crop, sms_text=sms_text, officer_brief=officer_brief,
        citations=citations, confidence=confidence, caveats=caveats, channel=channel))
    return {"ok": True, "action_id": aid, "status": "PENDING_APPROVAL", "note": "NOT sent. Held for a named officer."}

@mcp.tool(annotations=WRITE)
@logged
def file_flag(household_id: str, kind: str, reason: str, citations: list[str]) -> dict:
    """Raise a flag for officer action: input_order_request | credit_flag | pest_followup_visit | record_review.
    Creates a PENDING_APPROVAL item only; nothing is ordered or filed with a lender until an officer approves."""
    r = data.household(household_id)
    if not r: return {"ok": False, "error": f"unknown household {household_id}"}
    if kind not in FLAGS: return {"ok": False, "error": f"kind must be one of {sorted(FLAGS)}"}
    if (e := _check_cites(citations)): return {"ok": False, "error": e}
    aid = store.create(RUN_ID, "flag", household_id, r["collective_id"], dict(kind=kind, reason=reason, citations=citations))
    return {"ok": True, "action_id": aid, "status": "PENDING_APPROVAL"}

@mcp.tool(annotations=WRITE)
@logged
def schedule_followup(household_id: str, due_date: str, purpose: str, citations: list[str]) -> dict:
    """Schedule a follow-up visit/call (ISO date within 120 days of today). Pending until an officer approves."""
    r = data.household(household_id)
    if not r: return {"ok": False, "error": f"unknown household {household_id}"}
    d = date.fromisoformat(due_date); t = data.as_of()
    if not (t <= d <= t + timedelta(days=120)): return {"ok": False, "error": f"due_date must be between {t} and {t + timedelta(days=120)}"}
    if (e := _check_cites(citations)): return {"ok": False, "error": e}
    aid = store.create(RUN_ID, "followup", household_id, r["collective_id"], dict(due_date=due_date, purpose=purpose, citations=citations))
    return {"ok": True, "action_id": aid, "status": "PENDING_APPROVAL"}

if __name__ == "__main__":
    mcp.run()
