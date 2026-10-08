"""LangGraph orchestration:  start -> work -> verify -> (retry work) -> approval_gate -> dispatch.
Two MCP servers: csa-extension (ours) and mcp-server-time (official, borrowed).
Backends: 'rules' (deterministic planner, no model, offline) or 'llm' (open-weights via OpenAI-compatible endpoint)."""
import asyncio, json, os, shlex, sys, time, uuid
from contextlib import AsyncExitStack
from typing import Any, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from csa import audit, data, dispatcher, policy, store
from csa.llm import LLM, mcp_tools_to_openai

def time_cmd() -> list[str]:
    """Borrowed official server (modelcontextprotocol/servers: mcp-server-time). Run via uvx so it gets its own
    isolated environment (it pins mcp<2, we use mcp 2.x). Override with CSA_TIME_CMD."""
    if os.environ.get("CSA_TIME_CMD"): return shlex.split(os.environ["CSA_TIME_CMD"])
    import shutil
    uvx = shutil.which("uvx") or os.path.join(os.path.dirname(sys.executable), "uvx")
    return [uvx, "mcp-server-time"]

class State(TypedDict, total=False):
    cluster_id: str; hids: list[str]; todo: list[str]; attempt: int; feedback: dict; failures: list; gate: dict; dispatched: list

class Ctx:
    def __init__(self, run_id, backend, say):
        self.run_id, self.backend, self.say = run_id, backend, say
        self.llm = LLM() if backend == "llm" else None
        self.n_calls = 0; self.sessions: dict[str, ClientSession] = {}; self.tools: dict[str, list] = {}; self.t0 = time.time()
        self.cache: dict[str, Any] = {}

    async def open(self, stack: AsyncExitStack):
        env = {**os.environ, "CSA_RUN_ID": self.run_id}
        specs = {"csa": StdioServerParameters(command=sys.executable, args=["-m", "csa.mcp_server"], env=env),
                 "time": StdioServerParameters(command=time_cmd()[0], args=time_cmd()[1:], env=env)}
        for name, p in specs.items():
            r, w = await stack.enter_async_context(stdio_client(p))
            s = await stack.enter_async_context(ClientSession(r, w)); await s.initialize()
            self.sessions[name] = s; self.tools[name] = (await s.list_tools()).tools
        self.say(f"MCP servers up: csa-extension (built, {len(self.tools['csa'])} tools) + mcp-server-time (borrowed, {len(self.tools['time'])} tools)")

    async def call(self, server, tool, args, retry=True):
        t0 = time.time(); self.n_calls += 1
        try:
            res = await self.sessions[server].call_tool(tool, args)
            txt = "".join(c.text for c in res.content if getattr(c, "text", None)); out = json.loads(txt) if txt.strip().startswith(("{", "[")) else {"ok": not res.is_error, "text": txt}
            if res.is_error and "ok" not in out: out = {"ok": False, "error": txt}
        except Exception as e:
            if retry: self.say(f"  ! {tool} transport error ({e}); retrying once"); return await self.call(server, tool, args, retry=False)
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if server == "time":  # borrowed server doesn't know our audit log, so we log its calls client-side
            audit.append(self.run_id, "agent", "tool_call", server="mcp-server-time", tool=tool, inputs=args, outputs=out, ms=round((time.time() - t0) * 1000, 1))
        short = json.dumps(args)[:110]; res_s = ("OK " if out.get("ok", True) else "ERR ") + json.dumps({k: v for k, v in out.items() if k not in ("ok",)})[:130]
        self.say(f"  [{server}] {tool}({short}) -> {res_s}")
        return out

    # cached read helpers (rules backend)
    async def cached(self, key, tool, args):
        if key not in self.cache: self.cache[key] = await self.call("csa", tool, args)
        return self.cache[key]

# ---------------------------------------------------------------- backends
async def work_rules(ctx: Ctx, hid: str, feedback=None):
    plot = await ctx.call("csa", "get_household_plot", {"household_id": hid})
    if not plot.get("ok"):
        ctx.say(f"  ! cannot read {hid}: {plot.get('error')}; no advice drafted"); return
    dup = None
    if plot["possible_duplicate_of"]:
        o = await ctx.call("csa", "get_household_plot", {"household_id": plot["possible_duplicate_of"]})
        if o.get("ok") and all(o[k] == plot[k] for k in ("crop", "soil", "plot_acres", "yield_history_raw")): dup = o
    pest = rain = price = None; proxy = None
    if plot["crop_stage"] in ("emergence", "vegetative"):
        pest = await ctx.cached(f"pest:{plot['ward']}", "get_pest_alerts", {"ward": plot["ward"]})
    elif plot["stored_bags"] > 0:
        price = await ctx.cached(f"price:{plot['crop']}", "get_market_prices", {"crop": plot["crop"]})
    elif not dup:
        args = {"station_id": plot["station_id"], "zone_id": plot["zone_id"], "ward": plot["ward"]}
        rain = await ctx.cached(f"rain:{args}", "get_rainfall_signal", args)
        if rain.get("status") == "no_station" and rain.get("fallback"):
            fb = rain["fallback"]; ctx.say(f"  ~ recovery: no station for {plot['ward']}; retrying with {fb['station']} as labelled proxy")
            args = {"station_id": fb["station"], "zone_id": plot["zone_id"], "ward": plot["ward"]}
            rain = await ctx.cached(f"rain:{args}", "get_rainfall_signal", args); proxy = fb
        elif not rain.get("ok") or rain.get("status") == "no_station":
            ctx.say("  ! rainfall unavailable and no fallback; drafting WAIT/low-confidence is impossible without a source"); return
    plan = policy.decide(plot, rain, pest, price, data.as_of(), dup, proxy)
    if plan["advisory"]:
        a = plan["advisory"]; await ctx.call("csa", "draft_advisory", {"household_id": hid, **a})
    for f in plan["flags"]: await ctx.call("csa", "file_flag", {"household_id": hid, **f})
    for f in plan["followups"]: await ctx.call("csa", "schedule_followup", {"household_id": hid, **f})

SYSTEM = ("You are the drafting agent for a county agricultural extension office. You prepare advice for ONE household at a time. "
          "You never send anything: draft_advisory, file_flag and schedule_followup only create drafts for a named officer to approve. "
          "Gather what you need with the read tools, then draft. Cite only source_id values the tools returned. "
          "Prepare exactly one advisory (unless rule 1 applies). When done, reply with the single word DONE.\n\n" + policy.RULES_TEXT)

async def work_llm(ctx: Ctx, hid: str, feedback=None):
    allow = {"get_household_plot", "get_rainfall_signal", "get_pest_alerts", "get_market_prices", "draft_advisory", "file_flag", "schedule_followup"}
    tools = mcp_tools_to_openai(ctx.tools["csa"], allow)
    user = f"Household: {hid}. Today (data as-of date): {data.as_of().isoformat()}."
    if feedback: user += f"\nYour previous attempt was withdrawn by the independent self-check: {feedback}. Fix it."
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    for _ in range(14):
        m = await ctx.llm.chat(msgs, tools); msgs.append(m)
        calls = m.get("tool_calls") or []
        if not calls: break
        for c in calls:
            name = c["function"]["name"]
            try: args = json.loads(c["function"]["arguments"] or "{}")
            except Exception: args = None
            if name not in allow or not isinstance(args, dict): res = {"ok": False, "error": "invalid tool call"}
            else: res = await ctx.call("csa", name, args)
            msgs.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(res)[:6000]})

# ---------------------------------------------------------------- graph
def build_graph(ctx: Ctx, cluster_ids: list[str], max_attempts=2):
    async def start(s: State):
        now = await ctx.call("time", "get_current_time", {"timezone": "Africa/Nairobi"})
        hids = []
        for cid in cluster_ids:
            r = await ctx.call("csa", "list_households", {"collective_id": cid})
            hids += [h["household_id"] for h in r.get("households", [])]
        ctx.say(f"Plan: {len(hids)} households in {cluster_ids}; data as-of {data.as_of()}; issued {now.get('datetime','?')}")
        audit.append(ctx.run_id, "agent", "plan", clusters=cluster_ids, households=hids, backend=ctx.backend, model=getattr(ctx.llm, "model", None))
        return {"hids": hids, "todo": hids, "attempt": 0, "feedback": {}}

    async def work(s: State):
        for hid in s["todo"]:
            ctx.say(f"-- {hid}" + (f" (attempt {s['attempt']+1})" if s["attempt"] else ""))
            await (work_llm if ctx.backend == "llm" else work_rules)(ctx, hid, s["feedback"].get(hid))
        return {}

    async def verify(s: State):
        """Independent self-check: re-fetch evidence with read tools and compare against what was drafted."""
        acts = [a for a in store.listing(run_id=ctx.run_id) if a["status"] == "PENDING_APPROVAL"]
        adv = {a["household_id"]: a for a in acts if a["kind"] == "advisory"}
        flg = {a["household_id"] for a in acts if a["kind"] == "flag"}
        fails: dict[str, str] = {}
        for hid in s["hids"]:
            a = adv.get(hid)
            if not a:
                if hid not in flg: fails[hid] = "no advisory or flag was produced"
                continue
            p = a["payload"]; plot = await ctx.call("csa", "get_household_plot", {"household_id": hid})
            if p["recommendation"] == "PLANT":
                r = await ctx.call("csa", "get_rainfall_signal", {"station_id": plot["station_id"], "zone_id": plot["zone_id"], "ward": plot["ward"]})
                if r.get("status") == "no_station" or r.get("onset_status") != "MET":
                    fails[hid] = f"PLANT is not supported by the evidence (station={plot['station_id']}, onset={r.get('onset_status', r.get('status'))})"
            elif p["recommendation"] == "SPRAY":
                pa = await ctx.call("csa", "get_pest_alerts", {"ward": plot["ward"]})
                if not any(x["crop"] == plot["crop"] for x in pa.get("fresh", [])): fails[hid] = "SPRAY without a fresh pest alert for this crop"
            elif p["recommendation"] in ("HOLD", "SELL") and not any(c.startswith("PR-") for c in p["citations"]):
                fails[hid] = "HOLD/SELL without a price citation"
            if hid in fails:
                dispatcher.decide(ctx.run_id, a["id"], "reject", "system:self-check", mode="automatic", note=fails[hid])
                ctx.say(f"  x self-check withdrew draft {a['id']} for {hid}: {fails[hid]}")
        if fails: ctx.say(f"Self-check: {len(fails)} problem(s) found")
        else: ctx.say("Self-check: all drafts consistent with independently re-fetched evidence")
        audit.append(ctx.run_id, "agent", "self_check", failures=fails, attempt=s["attempt"])
        return {"failures": list(fails), "feedback": fails, "todo": list(fails), "attempt": s["attempt"] + 1}

    def after_verify(s: State):
        return "work" if (s["failures"] and s["attempt"] < max_attempts and ctx.backend == "llm") else "gate"

    async def gate(s: State):
        pend = store.listing(run_id=ctx.run_id, status="PENDING_APPROVAL")
        if not ctx.cache.get("gate_said"):  # a LangGraph node re-runs from the top when resumed after interrupt()
            ctx.cache["gate_said"] = True; ctx.say(f"GATE: {len(pend)} item(s) waiting for a named officer. Nothing has been sent, ordered or filed.")
        if not pend: return {"gate": {"approved": 0, "rejected": 0, "refused": 0}}
        resp = interrupt({"run_id": ctx.run_id, "pending": [{"id": a["id"], "kind": a["kind"], "household_id": a["household_id"], "payload": a["payload"]} for a in pend]})
        officer, mode = resp.get("officer"), resp.get("mode", "interactive"); cnt = {"approved": 0, "rejected": 0, "refused": 0, "deferred": 0}
        for a in pend:
            d = resp["items"].get(a["id"])
            if not d: cnt["deferred"] += 1; continue
            try:
                dispatcher.decide(ctx.run_id, a["id"], d["decision"], officer, mode=mode, note=d.get("note", ""), edited_sms=d.get("edited_sms"))
                cnt["approved" if d["decision"] == "approve" else "rejected"] += 1
            except dispatcher.GateError as e:
                cnt["refused"] += 1; ctx.say(f"  GATE REFUSED {a['id']}: {e}")
        return {"gate": cnt}

    async def dispatch(s: State):
        done = []
        for a in store.listing(run_id=ctx.run_id, status="APPROVED"):
            try: dispatcher.execute(ctx.run_id, a["id"]); done.append(a["id"]); ctx.say(f"  dispatched {a['id']} ({a['kind']}, {a['household_id']}) approved by {a['decided_by']}")
            except dispatcher.GateError as e: ctx.say(f"  NOT dispatched {a['id']}: {e}")
        return {"dispatched": done}

    g = StateGraph(State)
    for n, f in (("start", start), ("work", work), ("verify", verify), ("gate", gate), ("dispatch", dispatch)): g.add_node(n, f)
    g.add_edge(START, "start"); g.add_edge("start", "work"); g.add_edge("work", "verify")
    g.add_conditional_edges("verify", after_verify, {"work": "work", "gate": "gate"})
    g.add_edge("gate", "dispatch"); g.add_edge("dispatch", END)
    return g.compile(checkpointer=MemorySaver())

async def run(clusters: list[str], backend: str, decider, say=print, run_id: str | None = None, detach=False) -> dict:
    """decider(pending_payload) -> {'officer','mode','items':{id:{'decision',...}}}. detach=True stops at the gate."""
    run_id = run_id or f"run-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    ctx = Ctx(run_id, backend, say)
    async with AsyncExitStack() as stack:
        await ctx.open(stack)
        graph = build_graph(ctx, clusters); cfg = {"configurable": {"thread_id": run_id}}
        out = await graph.ainvoke({"cluster_id": ",".join(clusters)}, cfg)
        if "__interrupt__" in out:
            if detach:
                say(f"Detached at the gate. Review with: python -m csa.cli review --run {run_id}")
            else:
                resp = await decider(out["__interrupt__"][0].value)
                out = await graph.ainvoke(Command(resume=resp), cfg)
    acts = store.listing(run_id=run_id)
    summary = {"run_id": run_id, "backend": backend, "model": getattr(ctx.llm, "model", None), "elapsed_s": round(time.time() - ctx.t0, 1),
               "tool_calls": ctx.n_calls, "tokens": ctx.llm.usage if ctx.llm else {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0},
               "actions": {st: sum(1 for a in acts if a["status"] == st) for st in sorted({a["status"] for a in acts})}, "gate": out.get("gate")}
    audit.append(run_id, "agent", "run_summary", **{k: v for k, v in summary.items() if k != "run_id"})
    return summary
