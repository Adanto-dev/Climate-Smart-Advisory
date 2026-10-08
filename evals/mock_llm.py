"""A MOCK OpenAI-compatible server that behaves like a tool-calling model. It is NOT a language model.
It exists to test the 'llm' backend plumbing (tool schemas, tool-call loop, validation, self-check, retry)
without a GPU. Results from it say nothing about the quality of Qwen/Llama/etc. - see EVALS.md."""
import json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from csa import data, policy

MODE = {"m": "good"}   # good | bad

def _calls(msgs):  # tool results so far, by tool name -> last parsed JSON
    ids = {}; out = {}
    for m in msgs:
        for c in m.get("tool_calls") or []: ids[c["id"]] = c["function"]["name"]
        if m["role"] == "tool": out.setdefault(ids.get(m["tool_call_id"]), []).append(json.loads(m["content"]))
    return out

def respond(msgs):
    user = next(m["content"] for m in msgs if m["role"] == "user"); hid = user.split("Household: ")[1].split(".")[0]
    retry = "withdrawn" in user; r = _calls(msgs); n = [0]
    def tc(name, args):
        n[0] += 1; return {"id": f"c{len(msgs)}_{n[0]}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    if any(m["role"] == "assistant" and any(c["function"]["name"] in ("draft_advisory", "file_flag") for c in m.get("tool_calls") or []) for m in msgs):
        # a write already happened: if it was rejected for bad citations, redo it with real ones
        errs = [x for x in r.get("draft_advisory", []) if not x.get("ok")]
        if errs and "fabricated" not in json.dumps(msgs[-3:]): pass
        if errs and not any(x.get("ok") for x in r.get("draft_advisory", [])):
            plot = r["get_household_plot"][0]; rain = r["get_rainfall_signal"][-1]
            plan = policy.decide(plot, rain, None, None, data.as_of(), None, None); a = plan["advisory"]
            return {"role": "assistant", "content": None, "tool_calls": [tc("draft_advisory", {"household_id": hid, **a})]}
        return {"role": "assistant", "content": "DONE"}
    if "get_household_plot" not in r: return {"role": "assistant", "content": None, "tool_calls": [tc("get_household_plot", {"household_id": hid})]}
    plot = r["get_household_plot"][0]
    dup = None
    if plot["possible_duplicate_of"]:
        if len(r["get_household_plot"]) < 2: return {"role": "assistant", "content": None, "tool_calls": [tc("get_household_plot", {"household_id": plot["possible_duplicate_of"]})]}
        o = r["get_household_plot"][1]; dup = o if all(o[k] == plot[k] for k in ("crop", "soil", "plot_acres", "yield_history_raw")) else None
    pest = price = rain = proxy = None
    if plot["crop_stage"] in ("emergence", "vegetative"):
        if "get_pest_alerts" not in r: return {"role": "assistant", "content": None, "tool_calls": [tc("get_pest_alerts", {"ward": plot["ward"]})]}
        pest = r["get_pest_alerts"][0]
    elif plot["stored_bags"] > 0:
        if "get_market_prices" not in r: return {"role": "assistant", "content": None, "tool_calls": [tc("get_market_prices", {"crop": plot["crop"]})]}
        price = r["get_market_prices"][0]
    elif not dup:
        if "get_rainfall_signal" not in r: return {"role": "assistant", "content": None, "tool_calls": [tc("get_rainfall_signal", {"station_id": plot["station_id"], "zone_id": plot["zone_id"], "ward": plot["ward"]})]}
        rain = r["get_rainfall_signal"][-1]
        if rain.get("status") == "no_station":
            fb = rain["fallback"]; return {"role": "assistant", "content": None, "tool_calls": [tc("get_rainfall_signal", {"station_id": fb["station"], "zone_id": plot["zone_id"], "ward": plot["ward"]})]}
        if len(r["get_rainfall_signal"]) > 1: proxy = (r["get_rainfall_signal"][0].get("fallback"))
    plan = policy.decide(plot, rain, pest, price, data.as_of(), dup, proxy); calls = []
    if plan["advisory"]:
        a = dict(plan["advisory"])
        if MODE["m"] == "bad" and not retry:
            if hid == "HH-006": a.update(recommendation="PLANT", sms_text="Rains have started, plant now.")   # unsupported by evidence: data gap
            if hid == "HH-001": a["citations"] = a["citations"] + ["RF-ST-KAV-2026-10-11"]                       # fabricated source id
        calls.append(tc("draft_advisory", {"household_id": hid, **a}))
    for f in plan["flags"]: calls.append(tc("file_flag", {"household_id": hid, **f}))
    for f in plan["followups"]: calls.append(tc("schedule_followup", {"household_id": hid, **f}))
    return {"role": "assistant", "content": None if calls else "DONE", "tool_calls": calls or None}

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msg = respond(body["messages"]); msg = {k: v for k, v in msg.items() if v is not None}
        out = json.dumps({"choices": [{"message": msg}], "usage": {"prompt_tokens": 0, "completion_tokens": 0}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
    def log_message(self, *a): pass

def start(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"
