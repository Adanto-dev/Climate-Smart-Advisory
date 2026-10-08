# ARCHITECTURE.md

**Agent shape.** A LangGraph state machine, not a single model call in a loop: `start → work → verify → (retry work) → approval_gate → dispatch`. `work` drafts per household; `verify` is an independent self-check that re-fetches evidence with read tools and withdraws unsupported drafts; `approval_gate` uses LangGraph `interrupt()` so the graph literally pauses until a named officer answers; `dispatch` is the only stage that can make anything leave the system. Recovery behaviours: a station with no data → retry with a labelled proxy (which can never yield PLANT); a tool error → one retry; rejected citation → the model must re-draft with real ids; failed self-check → withdraw and (llm backend) retry up to twice.

**Orchestration.** LangGraph (MIT, open source) with an in-process checkpointer. Two backends behind the same graph: `rules` (deterministic planner, no model; makes the repo runnable offline and the rules unit-testable) and `llm` (OpenAI-compatible tool-calling loop for an open-weights model served locally, e.g. Qwen via Ollama, so household and yield records never leave the country).

**MCP servers — built.** `csa-extension`, 8 tools in 2 groups. *Read* (5): household plot with a data-quality list, rainfall signal with the onset rule shown, pest alerts with stale ones split out, market prices with outliers removed, household listing. *Write* (3, draft-only): `draft_advisory`, `file_flag`, `schedule_followup`. Boundaries are chosen so another extension app could reuse them: each returns source ids, and every write validates that its citations were actually served by a read tool in the same session. Why built: the value is in the data-quality handling and the cite-or-reject contract, which no generic server provides.

**MCP servers — borrowed.** `mcp-server-time` (official modelcontextprotocol/servers). Timezone arithmetic is a solved problem with subtle failure modes; reusing it costs one line and is audited like any other call. Run via `uvx` in its own environment because it pins an older `mcp`.

**Human in the loop.** Approval is not an MCP tool, so a model cannot call it. `dispatcher.decide` refuses approvals without a human full name; `dispatcher.execute` re-checks the approver and the SHA-256 of the exact approved content, so an edit after approval is refused. Gated actions: advisory to a farmer (SMS / USSD / home-visit list), input-order request, credit flag, follow-up booking, record-review flag. Officers can edit the SMS text; the edit is logged with old and new text.

**Audit.** One hash-chained JSONL written by the MCP server, the client and the dispatcher: timestamp (UTC), run id, actor, tool, inputs, outputs, errors, latency, approver and approval mode (`interactive` / `simulated` / `cli`). `csa audit verify` detects tampering. Cost per run is in the `run_summary` entry (tool calls, tokens, seconds).

**Data flow.** Synthetic CSV/JSON → `csa/data.py` (normalises, reports quality problems instead of hiding them) → MCP read tools → agent → MCP write tools → SQLite `PENDING_APPROVAL` → officer → dispatcher → `runs/outbox/*.jsonl` (gateway stubs).

**Deliberately out of scope.** Real SMS/USSD gateways, officer authentication, multi-office tenancy, local-language generation, learning from outcomes.
