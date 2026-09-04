# RecoverAI — QA / Break-It Report

- **Date:** 2026-09-04
- **Target:** http://localhost:8000 (RecoverAI dashboard + API)
- **Method:** API attack suite (hostile inputs, state abuse, webhook fuzzing, concurrency races) + browser exploratory testing (agent-browser)
- **Result:** 7 confirmed bugs → **all 7 fixed** → re-verified live + 11/11 tests passing
- **Evidence:** screenshots in `dogfood-output/screenshots/`, repro video attempt in `dogfood-output/videos/`

---

## Confirmed & fixed

### ISSUE-001 (Critical) — Live webhook signatures would always fail
- **Found by:** fuzzing signed webhooks through the HTTP route.
- **Symptom:** events that passed the route's signature check were rejected by `ingest_event` with `invalid_signature`.
- **Root cause:** `ingest_event` re-serialized the parsed JSON with `json.dumps(separators=(",",":"))` and verified the signature against *that*, not the raw bytes the sender signed. Any client whose byte-format differs (whitespace, key order, unicode escaping) — i.e., every real Razorpay webhook — would be rejected.
- **Fix:** `ingest_event(event, raw_body, signature, event_id)` verifies against the exact raw body; route and worldsim both pass their original bytes.
- **Re-verify:** signed events now ingest: `{"status":"accepted"}`.

### ISSUE-002 (Critical) — Opted-out customers loop through human approval forever
- **Found by:** reasoning from inbox data (two opted-out cases sitting in the Human Approval inbox), then confirming live.
- **Repro:** case #91 (opted-out, escalated) → `POST /api/approvals/91/approve` → 200 `stop_reason: escalated_to_human` → case **still in inbox** (count unchanged). The policy gate blocks every customer-facing action (opt-out), routing sends it back to escalate. Operator clicks approve forever, zero feedback.
- **Fix:** opted-out/DND violations now route to **write_off** (the compliant terminal — no approval can make contacting them legal), with the reason audited. State machine already allowed ESCALATED→…; verified `#91` and `#185` approve → `written_off` → leave inbox (46→40 across QA session), audit shows `reason: mandate_relink: customer opted out; …`.
- **Evidence:** `screenshots/optout-after-approve.png`, timeline API output in session log.

### ISSUE-003 (High) — Implausible webhook amounts corrupt the money metrics
- **Found by:** fuzzing amounts after ISSUE-001's fix unblocked ingestion.
- **Repro:** signed `payment.failed` with `amount: 10^18` → case created → `/stats` at-risk jumped to ₹10 quadrillion, recovery rate 36.1% → **0.0%**. Negative and zero amounts also ingested.
- **Fix:** normalizer rejects `amount <= 0` or `> ₹10,00,000` with an audited `event_rejected` record. Poisoned test case removed; stats restored (186 cases, ₹2,21,614).

### ISSUE-004 (High) — Invalid state filter → 500
- **Repro:** `GET /api/cases?state=garbage` → 500 Internal Server Error (unhandled `ValueError` from enum cast).
- **Fix:** explicit validation → 400 with the list of valid states.

### ISSUE-005 (High) — Malformed webhook bodies → 500
- **Repro:** valid signature + `{not json` → 500; valid signature + `[1,2,3]` → 500 (`.get` on a list).
- **Fix:** JSON parse wrapped → 400 `malformed JSON body`; non-dict payloads → 400 `event payload must be a JSON object`.

### ISSUE-006 (Medium) — Audit log ghosts from previous DB generations
- **Found by:** browser replay of case #91 showing **Aug 25** events (previous run's DB) mixed with Sep 4 events.
- **Root cause:** `audit.jsonl` is append-only but case ids restart when the DB is regenerated; replays by `case_id` pick up the old generation's events.
- **Fix:** batch generator rotates the audit file when seeding a fresh DB (`audit_YYYYMMDD_HHMMSS.jsonl`); current log cleaned of legacy entries (1,010 archived). Re-verified: case #91 replay now shows only the current run, ending in the audited write-off.

### ISSUE-007 (Low) — Replay timestamps showed time-of-day only
- **Repro:** replay modal of case #4 showed "16:14:15" with no date while the case also had events from another day — ordering reads as misleading.
- **Fix:** `fmtTs()` renders full locale date-time ("Sep 4, 4:22:57 PM"); write-off **reason** now also rendered in the trail.

---

## Attacked & held (no bug)

| Attack | Outcome |
|---|---|
| 404s: `/api/cases/99999/timeline`, approvals on missing ids | clean 404 |
| Non-integer path param | 422 validation error |
| Approve/reject on recovered/written-off/missing case | 400 with state explanation |
| Webhook: missing / bad signature | 400 `invalid signature` |
| Webhook: replayed event id | `duplicate_ignored` (idempotent) |
| Double-approve race (2 concurrent API calls) | exactly 1 processed, second → 400, exactly 1 attempt recorded |
| UI double-click on "approve & run" | exactly 1 attempt recorded |
| Write-off then approve | 400 |
| Filter dropdown (all states) | correct filtering |
| Empty-state dashboard (fresh DB) | clean zeros, "inbox empty", "no cases" — no NaN/crash |
| Console errors | none (only Tailwind CDN dev warning — cosmetic) |

## Minor notes (not fixed, by design/low value)
- Tailwind via CDN shows a production warning; fine for a demo, swap to a built stylesheet post-submission.
- 5s auto-refresh can make element refs stale between snapshot and click (automation quirk; humans won't notice).
- `?limit=-5` is clamped, not rejected — harmless.
