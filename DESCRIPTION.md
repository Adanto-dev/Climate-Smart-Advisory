# Climate-Smart Advisory — project description

**What it does.** Climate-Smart Advisory is an agent that helps an agricultural extension desk turn scattered rainfall, pest and price signals into household-level advice drafts. For each household in a collective it reads the plot record, fetches the rainfall onset signal and seasonal outlook, fresh pest alerts and clean market prices, and drafts one of: plant, wait, spray (scout), hold, or sell. Every recommendation carries the exact rainfall, pest, price or plot record IDs it came from, and the server rejects any citation the agent did not actually retrieve. The agent also files flags (input-order request, pest follow-up visit, record review) and schedules follow-ups.

**It never acts on its own.** The agent only creates drafts. A LangGraph interrupt pauses the run and a named officer approves, rejects or edits each item before anything is sent by SMS/USSD/home visit, ordered, or flagged for credit. Approval is bound to a hash of the exact content, and every call, approval and dispatch lands in a tamper-evident audit log.

**Handles messy data.** A missing rainfall dekad produces a low-confidence WAIT; a station with no data triggers a retry with a labelled proxy that can never produce a planting recommendation; stale pest alerts and a price entry error are excluded and disclosed; duplicate households, missing plot sizes and households without phones are flagged for officer review. An independent self-check re-fetches evidence and withdraws drafts the evidence does not support.

**Stack.** Own MCP server (8 tools: 5 read, 3 draft-only write); borrowed official `mcp-server-time`; LangGraph orchestration; deterministic rules backend plus an OpenAI-compatible backend for open-weights models served in-country. MIT licensed.

**Sub-theme.** Agriculture & Food Security → Climate-smart advisory (when to plant, when to spray, when to hold).

**Office and workflow.** A county/district/LGA extension desk of two or three officers preparing weekly advisories for collectives of smallholders. The agent replaces the manual cross-checking; the officer keeps the decision.

**Honest status.** Data is synthetic; no officer or farmer has reviewed the rules; 16 of 17 eval cases pass, with one documented failure (planting date is not cross-checked against onset). The open-weights path is implemented and plumbing-tested against a mock model, but a real open-weights run has not yet been recorded.
