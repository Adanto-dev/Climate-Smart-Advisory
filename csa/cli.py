import argparse, asyncio, json, os, sys
from csa import agent, audit, dispatcher, store

def C(code, s): return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s

def show(p):
    a = p["payload"]; h = f"{p['id']}  {p['kind'].upper():8} {p['household_id']}"
    if p["kind"] == "advisory":
        print(C("1", h), f"-> {a['recommendation']} ({a['confidence']} confidence, via {a['channel']})")
        print("   SMS:", a["sms_text"]); print("   Why:", a["officer_brief"])
        print("   Sources:", ", ".join(a["citations"]))
        for c in a["caveats"]: print("   Caveat:", c)
    elif p["kind"] == "flag": print(C("1", h), f"-> {a['kind']}: {a['reason']}\n   Sources:", ", ".join(a["citations"]))
    else: print(C("1", h), f"-> follow-up {a['due_date']}: {a['purpose']}")

async def interactive(payload):
    print("\n" + C("33;1", "=== OFFICER REVIEW — nothing leaves until you approve ==="))
    officer = input("Officer full name (required): ").strip(); items = {}
    for p in payload["pending"]:
        print(); show(p)
        while True:
            k = input("  [a]pprove / [r]eject / [e]dit sms / [s]kip > ").strip().lower()[:1]
            if k == "a": items[p["id"]] = {"decision": "approve"}
            elif k == "r": items[p["id"]] = {"decision": "reject", "note": input("  reason: ")}
            elif k == "e" and p["kind"] == "advisory": items[p["id"]] = {"decision": "approve", "edited_sms": input("  new text: "), "note": "edited by officer"}
            elif k == "s": pass
            else: continue
            break
    return {"officer": officer, "mode": "interactive", "items": items}

def scripted(officer):
    async def f(payload):
        return {"officer": officer, "mode": "simulated", "items": {p["id"]: {"decision": "approve"} for p in payload["pending"]}}
    return f

def main():
    ap = argparse.ArgumentParser(prog="csa"); sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--clusters", default="KAV-A,MUT-B,NDU-C"); r.add_argument("--backend", choices=["rules", "llm"], default="rules")
    r.add_argument("--yes-as", metavar="NAME", help="SIMULATED approval as NAME for CI/eval (logged as mode=simulated)"); r.add_argument("--detach", action="store_true")
    v = sub.add_parser("review"); v.add_argument("--run")
    d = sub.add_parser("decide"); d.add_argument("action_id"); d.add_argument("decision", choices=["approve", "reject"]); d.add_argument("--officer", required=True); d.add_argument("--run", required=True)
    x = sub.add_parser("dispatch"); x.add_argument("--run", required=True)
    au = sub.add_parser("audit"); au.add_argument("what", choices=["verify", "show"]); au.add_argument("--run")
    a = ap.parse_args()
    if a.cmd == "run":
        dec = scripted(a.yes_as) if a.yes_as else interactive
        s = asyncio.run(agent.run(a.clusters.split(","), a.backend, dec, detach=a.detach)); print("\nRUN SUMMARY", json.dumps(s, indent=1))
    elif a.cmd == "review":
        for p in store.listing(run_id=a.run): show(p); print("   status:", p["status"], "\n")
    elif a.cmd == "decide":
        dispatcher.decide(a.run, a.action_id, a.decision, a.officer, mode="cli"); print("recorded")
    elif a.cmd == "dispatch":
        for p in store.listing(run_id=a.run, status="APPROVED"): print(p["id"], dispatcher.execute(a.run, p["id"]))
    elif a.cmd == "audit":
        if a.what == "verify": ok, n, bad = audit.verify(); print(f"audit chain: {'OK' if ok else 'BROKEN at seq '+str(bad)} ({n} entries)"); sys.exit(0 if ok else 1)
        for e in audit.read(a.run): print(json.dumps(e)[:260])

if __name__ == "__main__": main()
