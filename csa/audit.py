"""Append-only, hash-chained audit log shared by every process (MCP server, agent, dispatcher)."""
import fcntl, hashlib, json, os
from datetime import datetime, timezone

def path() -> str:
    return os.environ.get("CSA_AUDIT_LOG", "runs/audit.jsonl")

def _h(rec: dict) -> str:
    return hashlib.sha256(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest()

def append(run_id: str, actor: str, kind: str, **fields) -> dict:
    p = path(); os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0); lines = f.read().splitlines()
        prev = json.loads(lines[-1])["hash"] if lines else "GENESIS"
        rec = {"seq": len(lines) + 1, "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
               "run_id": run_id, "actor": actor, "kind": kind, **fields, "prev": prev}
        rec["hash"] = _h(rec)
        f.write(json.dumps(rec, default=str) + "\n"); f.flush()
    return rec

def read(run_id: str | None = None) -> list[dict]:
    p = path()
    if not os.path.exists(p): return []
    out = [json.loads(l) for l in open(p) if l.strip()]
    return [r for r in out if run_id is None or r["run_id"] == run_id]

def verify() -> tuple[bool, int, int | None]:
    """Returns (ok, entries, first_bad_seq)."""
    prev, n = "GENESIS", 0
    for r in read():
        n += 1
        body = {k: v for k, v in r.items() if k != "hash"}
        if r["prev"] != prev or _h(body) != r["hash"]:
            return False, n, r["seq"]
        prev = r["hash"]
    return True, n, None
