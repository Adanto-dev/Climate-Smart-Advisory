# Climate-Smart Advisory — project description

**What it does.** Climate-Smart Advisory helps an agricultural extension desk turn scattered rainfall, pest and price signals into household-level advice drafts. For each household in a collective it reads the plot record, fetches the rainfall-onset signal and seasonal outlook, fresh pest alerts and clean market prices, and drafts one of: plant, wait, spray (scout), hold or sell. It also files flags (input-order request, pest follow-up visit, record review) and schedules follow-ups. Every recommendation carries the rainfall, pest, price or plot record IDs it came from, and the server rejects any citation the agent did not actually retrieve.

**It never acts on its own.** The agent only creates drafts. A LangGraph interrupt pauses the run; a named officer approves, rejects or edits each item before anything goes out by SMS, USSD or home visit, is ordered, or is flagged for credit. Approval is bound to a hash of the exact content, and every call, approval and dispatch is written to a tamper-evident audit log.

**Messy data.** A missing rainfall dekad gives a low-confidence WAIT; a station with no data triggers a retry on a labelled proxy that can never yield PLANT; stale pest alerts and a price entry error are excluded and disclosed; duplicate households and missing plot sizes go to the officer. An independent self-check re-fetches evidence and withdraws unsupported drafts.

**Stack.** Own MCP server (8 tools: 5 read, 3 draft-only write), the official `mcp-server-time`, LangGraph, and a backend for open-weights models served in-country (plus an offline rules backend). MIT licensed.

**Sub-theme.** Agriculture & Food Security — Climate-smart advisory.

**Office and workflow.** A county, district or LGA extension desk of two or three officers preparing weekly advisories for smallholder collectives. The agent does the cross-checking; the officer keeps the decision.

**Honest status.** Data is synthetic and no officer or farmer has reviewed the rules. 16 of 17 evals pass; one documented failure (planting date is not cross-checked against onset). The open-weights path is plumbing-tested on a mock model; a real open-weights run is not yet recorded.
