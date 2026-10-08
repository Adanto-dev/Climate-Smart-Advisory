import json, os
from datetime import date
import pytest
from csa import audit, dispatcher, policy, data

def plot(**k):
    base = dict(household_id="HH-X", source_id="SRC-HH-X", ward="W", crop="maize", soil="loam", plot_acres=1.0, crop_stage="none", planted_date=None,
                stored_bags=0, seed_in_stock=True, has_phone=True, preferred_channel="sms", data_quality=[], possible_duplicate_of=None)
    return {**base, **k}

def rain(status, mm=49.0, **k):
    d = [{"source_id": f"RF-S-2026-09-{i}", "mm": 1.0} for i in (1, 11, 21)]
    return {"onset_status": status, "two_dekad_total_mm": mm, "dekads": d, "station_id": "ST-X", "latest_is_provisional": False,
            "missing_dekads": ["2026-09-21"] if status == "INDETERMINATE" else [], "outlook": {"source_id": "OUT-1", "below": 0.2, "normal": 0.4, "above": 0.4, "season": "OND"}, **k}

def test_plant_when_onset_met_and_cited():
    a = policy.decide(plot(), rain("MET"), None, None, date(2026, 10, 7), None, None)["advisory"]
    assert a["recommendation"] == "PLANT" and "OUT-1" in a["citations"] and a["citations"][0] == "SRC-HH-X"

def test_proxy_never_plants():
    a = policy.decide(plot(), rain("MET"), None, None, date(2026, 10, 7), None, {"distance_km": 18})["advisory"]
    assert a["recommendation"] == "WAIT" and a["confidence"] == "low"

def test_data_gap_waits():
    assert policy.decide(plot(), rain("INDETERMINATE", None), None, None, date(2026, 10, 7), None, None)["advisory"]["recommendation"] == "WAIT"

def test_missing_plot_size_files_review_flag():
    out = policy.decide(plot(plot_acres=None), rain("MET"), None, None, date(2026, 10, 7), None, None)
    assert any(f["kind"] == "record_review" for f in out["flags"])

def test_officer_names():
    assert dispatcher.valid_officer("Grace Wanjiku")
    for bad in ("", "agent", "Claude", "system", "Grace", None, "auto approver"): assert not dispatcher.valid_officer(bad)

def test_audit_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("CSA_AUDIT_LOG", str(tmp_path / "a.jsonl"))
    for i in range(3): audit.append("r", "agent", "tool_call", n=i)
    assert audit.verify() == (True, 3, None)
    p = tmp_path / "a.jsonl"; p.write_text(p.read_text().replace('"n": 1', '"n": 9')); assert audit.verify()[0] is False

def test_unit_conversion():
    r = data.household("HH-004"); assert data.normalise_household(r)["plot_acres"] == 4.94
