"""The ONLY code that can make anything leave the system (SMS, input order, credit flag, visit booking).
It is not exposed through MCP. It refuses unless a NAMED HUMAN approved the exact content hash.
Outputs go to runs/outbox/ (a gateway stub: no real SMS is sent, no real order placed, no lender contacted)."""
import json, os, pathlib
from csa import audit, store

class GateError(Exception): pass

NOT_HUMAN = {"", "agent", "claude", "system", "auto", "ai", "llm", "bot", "assistant", "none", "null"}

def _outbox() -> pathlib.Path:
    p = pathlib.Path(os.environ.get("CSA_OUTBOX", "runs/outbox")); p.mkdir(parents=True, exist_ok=True); return p

def valid_officer(name: str | None) -> bool:
    n = (name or "").strip()
    return len(n) >= 3 and " " in n and n.lower() not in NOT_HUMAN and not n.lower().startswith(("agent", "system", "auto"))

def decide(run_id, aid, decision, officer, mode="interactive", note="", edited_sms=None):
    """decision: approve | reject. Approvals require a named human (first + last name). Rejections are always allowed
    (the self-check may withdraw a draft as 'system:self-check') because rejecting can never cause harm."""
    a = store.get(aid)
    if not a: raise GateError(f"unknown action {aid}")
    if a["status"] != "PENDING_APPROVAL": raise GateError(f"{aid} is {a['status']}, not pending")
    if decision == "approve":
        if not valid_officer(officer):
            audit.append(run_id, "gate", "gate_refused", action_id=aid, reason="approval needs a named human officer", offered=officer)
            raise GateError("approval refused: a named human officer (first and last name) is required")
        if edited_sms is not None and a["kind"] == "advisory":
            old = a["payload"]["sms_text"]; p = {**a["payload"], "sms_text": edited_sms[:320]}
            store.update(aid, payload=json.dumps(p), content_hash=store.chash(p))
            audit.append(run_id, "officer", "officer_edit", action_id=aid, officer=officer, old_sms=old, new_sms=p["sms_text"])
            a = store.get(aid)
        store.update(aid, status="APPROVED", decided_by=officer, decided_ts=store.now(), decision_note=note,
                     approved_hash=a["content_hash"], approval_mode=mode)
    elif decision == "reject":
        store.update(aid, status="REJECTED", decided_by=officer or "system", decided_ts=store.now(), decision_note=note, approval_mode=mode)
    else:
        raise GateError("decision must be approve or reject")
    audit.append(run_id, "officer" if officer and not str(officer).startswith("system") else "system", "approval",
                 action_id=aid, action_kind=a["kind"], household_id=a["household_id"], decision=decision, officer=officer,
                 approval_mode=mode, content_hash=a["content_hash"], note=note)

def execute(run_id, aid) -> dict:
    a = store.get(aid)
    if not a: raise GateError(f"unknown action {aid}")
    if a["status"] != "APPROVED" or not valid_officer(a["decided_by"]):
        audit.append(run_id, "gate", "gate_refused", action_id=aid, reason=f"status={a['status']}")
        raise GateError(f"{aid} not approved by a named officer (status {a['status']})")
    if store.chash(a["payload"]) != a["approved_hash"]:
        audit.append(run_id, "gate", "gate_refused", action_id=aid, reason="content changed after approval")
        raise GateError(f"{aid} content changed after approval; re-approval required")
    p, k = a["payload"], a["kind"]
    if k == "advisory":
        ch = p["channel"]; target = {"sms": "sms_outbox", "ussd": "ussd_outbox", "home_visit": "visit_list"}[ch]
        res = {"delivered_via": target, "stub": True, "text": p["sms_text"]}
    elif k == "flag":
        res = {"filed": p["kind"], "stub": True, "reason": p["reason"]}
    else:
        res = {"scheduled_for": p["due_date"], "stub": True, "purpose": p["purpose"]}
    entry = {"action_id": aid, "kind": k, "household_id": a["household_id"], "approved_by": a["decided_by"], "result": res, "ts": store.now()}
    fname = p["channel"] if k == "advisory" else ("flags" if k == "flag" else "followups")
    with open(_outbox() / f"{fname}.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
    store.update(aid, status="EXECUTED", executed_ts=store.now(), execution_result=json.dumps(res))
    audit.append(run_id, "dispatcher", "dispatch", action_id=aid, action_kind=k, household_id=a["household_id"], approved_by=a["decided_by"],
                 approval_mode=a["approval_mode"], content_hash=a["approved_hash"], result=res)
    return res
