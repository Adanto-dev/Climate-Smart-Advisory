"""Advisory rules, as a pure function over tool outputs (so they are unit-testable and auditable).
The same rules are given to the open-weights model as prose in RULES_TEXT; the verify node re-checks its output."""
from datetime import timedelta

RULES_TEXT = """RULES (follow exactly; cite only source_id values returned by tools):
1. If the plot record says possible_duplicate_of=X: fetch X, and if crop/soil/size/yields match, do NOT draft an advisory; file_flag record_review.
2. If crop is already planted (crop_stage emergence/vegetative) and get_pest_alerts shows a FRESH alert for that crop in the ward:
   draft SPRAY (scout this week, officer confirms product/threshold), file_flag pest_followup_visit, schedule_followup in 7 days. Stale alerts must never drive advice.
3. Else if stored_bags > 0: call get_market_prices(crop). HOLD if the mean clean-market trend is >= +5%, else SELL at best_clean_market. Never use outlier prices.
4. Else (planting decision) call get_rainfall_signal. onset_status MET -> PLANT; NOT_MET or INDETERMINATE -> WAIT (INDETERMINATE = data gap, confidence low).
   If station_id is null (status no_station): retry with the fallback station as a PROXY; a proxy can NEVER produce PLANT -> WAIT, confidence low, say it is a proxy.
   If outlook below-normal >= 0.40 and soil is sandy: caveat that sandy soil dries fast and the officer may prefer a drought-tolerant crop.
   If PLANT and seed_in_stock is false: file_flag input_order_request. If PLANT: schedule_followup 14 days (germination check).
5. If plot_acres is null: add caveat and file_flag record_review. If has_phone is false: channel=home_visit.
6. Latest dekad provisional -> confidence at most medium. Always include caveats for data_quality issues.
7. Keep sms_text under 320 chars, plain language, include the 'why' with the numbers. Never promise yields."""

def decide(plot, rain, pest, price, as_of, dup_match, proxy):
    """Return {'advisory': {...}|None, 'flags': [...], 'followups': [...]} for one household."""
    out = {"advisory": None, "flags": [], "followups": []}
    hid, sid = plot["household_id"], plot["source_id"]
    chan = "home_visit" if not plot["has_phone"] else ("ussd" if plot["preferred_channel"] == "ussd" else "sms")
    caveats = list(plot["data_quality"])
    if plot["plot_acres"] is None:
        out["flags"].append(dict(kind="record_review", reason="Plot size missing; seed and fertiliser quantities cannot be sized.", citations=[sid]))

    if plot["possible_duplicate_of"] and dup_match:
        out["flags"].append(dict(kind="record_review", citations=[sid, dup_match["source_id"]],
            reason=f"{hid} matches {dup_match['household_id']} on crop, soil, plot size and yields: likely duplicate registration. No advisory drafted until an officer resolves it."))
        return out

    fresh = [a for a in (pest or {}).get("fresh", []) if a["crop"] == plot["crop"]]
    if plot["crop_stage"] in ("emergence", "vegetative") and fresh:
        a = fresh[0]
        out["advisory"] = dict(recommendation="SPRAY", crop=plot["crop"], channel=chan, confidence="medium", caveats=caveats,
            citations=[sid, a["source_id"]],
            sms_text=f"{a['pest'].capitalize()} {'confirmed' if a['status']=='officer-verified' else 'reported'} in {plot['ward']} ward ({a['age_days']} days ago). Scout your {plot['crop']} this week: check 20 plants for fresh leaf damage. Your extension officer will confirm the control to use.",
            officer_brief=f"{a['pest']} alert {a['alert_id']} ({a['status']}, reported {a['reported']}, {a['age_days']}d old) covers {plot['crop']} in {plot['ward']}. Plot {sid} shows {plot['crop']} at {plot['crop_stage']} (planted {plot['planted_date']}). Scouting advised; product and action threshold are the officer's call.")
        out["flags"].append(dict(kind="pest_followup_visit", citations=[sid, a["source_id"]], reason=f"Verified {a['pest']} alert in ward; household has {plot['crop']} at {plot['crop_stage']}."))
        out["followups"].append(dict(due_date=(as_of + timedelta(days=7)).isoformat(), purpose="Check scouting result and control applied", citations=[sid, a["source_id"]]))
        return out

    if plot["stored_bags"] > 0 and price:
        ms = [m for m in price["markets"] if m["trend_pct"] is not None]
        tr = round(sum(m["trend_pct"] for m in ms) / len(ms), 1); best = price["best_clean_market"]
        cites = [sid] + [m[k] for m in ms for k in ("first_source_id", "latest_source_id")]
        ex = "; ".join(f"{o['source_id']} excluded as outlier ({o['reason']})" for o in price["outliers_excluded"])
        if ex: caveats.append("Outlier price excluded: " + ex)
        if tr >= 5:
            rec, sms = "HOLD", f"Maize prices at nearby markets rose about {tr}% over 4 weeks. Consider holding your {plot['stored_bags']} bags a little longer and check them for moisture and pests. Your officer will advise when to sell."
        else:
            rec, sms = "SELL", f"Best clean maize price this week is KES {best['latest_price']:.0f} per 90kg bag at {best['market_id']}. Prices are flat ({tr}%), so selling now is reasonable."
        out["advisory"] = dict(recommendation=rec, crop=plot["crop"], channel=chan, confidence="medium", caveats=caveats, citations=cites, sms_text=sms,
            officer_brief=f"Clean-market 4-week trend averages {tr}% across {len(ms)} markets (latest week {price['latest_week']}). Best clean price {best['latest_price']:.0f} at {best['market_id']}. Household has {plot['stored_bags']} bags stored. Yield history in bags, not comparable with kg/acre records.")
        return out

    # planting decision
    r = rain or {}; status = r.get("onset_status", "INDETERMINATE"); ol = r.get("outlook") or {}
    cites = [sid] + [d["source_id"] for d in r.get("dekads", [])[-3:]] + ([ol["source_id"]] if ol else [])
    conf = "high"
    if r.get("latest_is_provisional"): conf = "medium"; caveats.append("Latest rainfall dekad is provisional and may be revised.")
    mm = r.get("two_dekad_total_mm")
    if status == "INDETERMINATE":
        rec, conf = "WAIT", "low"
        caveats.append(f"Rainfall data gap at station {r.get('station_id')}: missing dekad(s) {', '.join(r.get('missing_dekads', []))}.")
        sms = "We cannot yet confirm that the rains have properly started in your area. Please wait for your extension officer's go-ahead before planting."
        why = "Onset cannot be assessed because of the missing rainfall dekad; waiting is the safe default."
    elif proxy:
        rec, conf = "WAIT", "low"
        caveats.append(f"No rainfall station for {plot['ward']}; used {r['station_id']} ({proxy['distance_km']} km away) as a PROXY.")
        sms = "Rain has fallen at the nearest station, but not yet confirmed locally. Please wait for your extension officer's go-ahead before planting."
        why = f"Proxy station {r['station_id']} shows onset {status} ({mm} mm in 2 dekads) but a proxy can never trigger a planting recommendation."
    elif status == "MET":
        rec = "PLANT"; why = f"Last two complete dekads total {mm} mm (rule: >= 40 mm)."
        sms = f"Rains have started: {mm}mm in the last 2 dekads at {r['station_id']} station (rule: 40mm). You can begin planting your {plot['crop']} now."
        if ol.get("below", 0) >= 0.40:
            caveats.append(f"Seasonal outlook tilts below-normal ({ol['below']:.0%}); expect possible dry spells.")
            if plot["soil"] == "sandy":
                caveats.append("Sandy soil dries fast; officer may prefer a drought-tolerant crop such as sorghum.")
                sms += " Your soil is sandy and dries fast - ask your officer about sorghum."
            conf = "medium" if conf == "high" else conf
    else:
        rec = "WAIT"; why = f"Last two complete dekads total {mm} mm, below the 40 mm onset rule."
        sms = f"Only {mm}mm of rain in the last 2 dekads (rule: 40mm). Please wait before planting."
    out["advisory"] = dict(recommendation=rec, crop=plot["crop"], channel=chan, confidence=conf, caveats=caveats, citations=cites, sms_text=sms[:320],
        officer_brief=f"{why} Outlook {ol.get('season','n/a')}: below {ol.get('below','n/a')}, normal {ol.get('normal','n/a')}, above {ol.get('above','n/a')}. Plot {sid}: {plot['crop']} on {plot['soil']} soil, {plot['plot_acres']} acres.")
    if rec == "PLANT":
        if not plot["seed_in_stock"]:
            out["flags"].append(dict(kind="input_order_request", citations=[sid], reason=f"Household has no seed in stock and onset is MET; request seed for {plot['plot_acres'] or 'unknown'} acres of {plot['crop']}."))
        out["followups"].append(dict(due_date=(as_of + timedelta(days=14)).isoformat(), purpose="Germination and stand check", citations=[sid] + cites[1:2]))
    return out
