# Demo video script (target 2:45, unedited screen recording of a real run)

Record the terminal only. Do not speed up or cut the run. Upload to YouTube/Vimeo as public.

| Time | On screen | Say |
|---|---|---|
| 0:00 | `./run.sh --backend llm` (open-weights model via Ollama; show `ollama list` first) | "Extension officers cannot visit every household. This agent drafts advice; an officer decides." |
| 0:15 | Tool calls scrolling: `get_household_plot`, `get_rainfall_signal`, `draft_advisory` | "Two MCP servers: one I built, one official time server. Every call is on screen and in the audit log." |
| 0:45 | HH-010: `no_station` → `~ recovery` retry with ST-KAV | "No rainfall station here, so it retries with a labelled proxy and refuses to recommend planting on it." |
| 1:10 | HH-006: missing dekad → WAIT, low | "A data gap becomes a low-confidence WAIT, not a guess." |
| 1:25 | Self-check line (`x self-check withdrew…` if the model produced one, otherwise "all consistent") | "An independent check re-fetches evidence and withdraws unsupported drafts." |
| 1:45 | `GATE: N item(s) waiting` → type officer name → review 3 items (approve one, edit one SMS, reject one) | "Nothing has been sent. A named officer approves, edits or rejects." |
| 2:15 | Try approving with name `agent` → refused | "The gate refuses non-human approvers." |
| 2:25 | `cat runs/outbox/sms.jsonl`, `python -m csa.cli audit verify` | "Only approved items were dispatched; the log is hash-chained." |
| 2:40 | Show a failure: `./run.sh evals` tail with E17 FAIL | "And here is one thing it still gets wrong: it doesn't cross-check planting date against onset." |
