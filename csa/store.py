"""SQLite store for pending/approved actions. The agent can only create PENDING_APPROVAL rows."""
import hashlib, json, os, sqlite3, uuid
from datetime import datetime, timezone

def db() -> sqlite3.Connection:
    p = os.environ.get("CSA_DB", "runs/state.db"); os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    c = sqlite3.connect(p, timeout=30); c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS actions(
      id TEXT PRIMARY KEY, run_id TEXT, kind TEXT, household_id TEXT, collective_id TEXT, payload TEXT,
      content_hash TEXT, status TEXT, created_ts TEXT, decided_by TEXT, decided_ts TEXT, decision_note TEXT,
      approved_hash TEXT, approval_mode TEXT, executed_ts TEXT, execution_result TEXT)""")
    return c

def now() -> str: return datetime.now(timezone.utc).isoformat(timespec="seconds")
def chash(payload: dict) -> str: return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

def create(run_id, kind, household_id, collective_id, payload) -> str:
    aid = f"{kind[:3].upper()}-{uuid.uuid4().hex[:8]}"
    with db() as c:
        c.execute("INSERT INTO actions(id,run_id,kind,household_id,collective_id,payload,content_hash,status,created_ts)"
                  " VALUES(?,?,?,?,?,?,?,?,?)",
                  (aid, run_id, kind, household_id, collective_id, json.dumps(payload), chash(payload), "PENDING_APPROVAL", now()))
    return aid

def get(aid) -> dict | None:
    r = db().execute("SELECT * FROM actions WHERE id=?", (aid,)).fetchone()
    if not r: return None
    d = dict(r); d["payload"] = json.loads(d["payload"]); return d

def listing(run_id=None, status=None) -> list[dict]:
    q, a = "SELECT * FROM actions WHERE 1=1", []
    if run_id: q += " AND run_id=?"; a.append(run_id)
    if status: q += " AND status=?"; a.append(status)
    out = []
    for r in db().execute(q + " ORDER BY created_ts, id", a).fetchall():
        d = dict(r); d["payload"] = json.loads(d["payload"]); out.append(d)
    return out

def update(aid, **kw):
    with db() as c:
        c.execute(f"UPDATE actions SET {','.join(k+'=?' for k in kw)} WHERE id=?", (*kw.values(), aid))
