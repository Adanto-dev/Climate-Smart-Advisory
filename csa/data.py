"""Loaders for the synthetic dataset. Everything returned carries a source_id so it can be cited."""
import csv, json, os, pathlib
from datetime import date

def D() -> pathlib.Path:
    return pathlib.Path(os.environ.get("CSA_DATA_DIR", pathlib.Path(__file__).resolve().parent.parent / "data"))

def meta() -> dict: return json.load(open(D() / "meta.json"))
def as_of() -> date: return date.fromisoformat(os.environ.get("CSA_AS_OF") or meta()["as_of"])
def rows(name): return list(csv.DictReader(open(D() / name)))
def jload(name): return json.load(open(D() / name))

ACRE_PER_HA = 2.47105

def household(hid: str) -> dict | None:
    for r in rows("households.csv"):
        if r["household_id"] == hid:
            return r
    return None

def normalise_household(r: dict) -> dict:
    """Clean a raw row and say what was wrong with it, rather than silently fixing it."""
    q = []
    size = None
    if r["plot_size"].strip():
        size = float(r["plot_size"])
        if r["plot_unit"] == "ha": size = round(size * ACRE_PER_HA, 2); q.append("plot size converted from hectares to acres")
    else:
        q.append("plot size missing - seed/fertiliser quantities cannot be sized")
    ys = [y.strip() for y in r["yield_history"].split(";")]
    if any("bag" in y for y in ys): q.append("yield history recorded in 90kg bags, not kg/acre - not comparable")
    if any(y == "" for y in ys): q.append("yield history has missing season(s)")
    if not r["phone"].strip(): q.append("no phone number on file - SMS impossible, home visit needed")
    if r["possible_duplicate_of"]: q.append(f"possible duplicate of {r['possible_duplicate_of']} (identical plot and yields)")
    return {
        "household_id": r["household_id"], "collective_id": r["collective_id"], "ward": r["ward"],
        "station_id": r["station_id"] or None, "zone_id": r["zone_id"], "crop": r["crop"], "soil": r["soil"],
        "plot_acres": size, "crop_stage": r["crop_stage"], "planted_date": r["planted_date"] or None,
        "stored_bags": int(r["stored_bags"]), "seed_in_stock": r["seed_in_stock"] == "yes",
        "has_phone": bool(r["phone"].strip()), "preferred_channel": r["channel"],
        "yield_history_raw": r["yield_history"], "possible_duplicate_of": r["possible_duplicate_of"] or None,
        "data_quality": q, "source_id": f"SRC-{r['household_id']}",
    }
