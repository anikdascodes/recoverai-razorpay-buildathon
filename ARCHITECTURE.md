# Track 03 — AI Revenue Recovery Agent: Engineering Architecture

> Working name: **RecoverAI**
> Goal: Detect revenue at risk on Razorpay test-mode APIs → diagnose → intervene → recover money, with compliant escalation, stopping rules, and a full audit trail. Measured money recovered across a batch.

---

## 1. Problem Scope (what we actually build)

One closed loop, executed end-to-end in test mode:

**Failed subscription recovery** (primary) + **checkout drop-off recovery** (secondary, same plumbing).

Why this scoping: subscriptions give clean webhook triggers (`payment.failed`, `subscription.pending`), a bounded retry surface, and a measurable outcome per case (recovered amount vs. at-risk amount). Checkout abandonment reuses the same pipeline with a different ingress signal.

Non-goals: no offense-capable scraping, no real customer contact, no production credentials. All runs on Razorpay test-mode keys + a synthetic 100–200 record batch of customers/plans.

---

## 2. High-Level Architecture

```
                        ┌─────────────────────────────────────────────────────────┐
                        │                     INGRESS LAYER                        │
                        │  ┌──────────────┐   ┌─────────────────┐  ┌───────────┐ │
                        │  │ Razorpay     │   │ Batch Generator │  │ Checkout  │ │
                        │  │ Webhook      │   │ (synthetic      │  │ Abandon   │ │
                        │  │ Receiver     │   │  failed subs)   │  │ Signal    │ │
                        │  └──────┬───────┘   └────────┬────────┘  └─────┬─────┘ │
                        └─────────┼────────────────────┼─────────────────┼───────┘
                                  ▼                    ▼                 ▼
                        ┌─────────────────────────────────────────────────────────┐
                        │              CASE NORMALIZER + DEDUPER                   │
                        │   (idempotent on x-razorpay-event-id / payment_id)       │
                        └──────────────────────────┬──────────────────────────────┘
                                                   ▼
                        ┌─────────────────────────────────────────────────────────┐
                        │            AGENT CORE (LangGraph state machine)          │
                        │                                                          │
                        │   ┌────────┐  ┌─────────┐  ┌──────────┐  ┌────────────┐ │
                        │   │ TRIAGE │─▶│DIAGNOSE │─▶│ POLICY   │─▶│  PLANNER   │ │
                        │   │ node   │  │ node    │  │ GATE     │  │ (LLM picks │ │
                        │   │        │  │ (root   │  │ (hard    │  │  channel & │ │
                        │   │        │  │ cause)  │  │ rules)   │  │  message)  │ │
                        │   └────────┘  └─────────┘  └──────────┘  └─────┬──────┘ │
                        │                                                  │      │
                        │      ┌──────────────┐  ┌──────────────┐         ▼      │
                        │      │  VERIFIER    │◀─│  EXECUTOR    │──────────────   │
                        │      │ (did money   │  │ (bounded     │  (runs action)  │
                        │      │  come back?) │  │  tools only) │                 │
                        │      └──────┬───────┘  └──────────────┘                 │
                        │             │                                           │
                        │             ▼                                           │
                        │      ┌──────────────┐  ┌──────────────┐                 │
                        │      │  STOP /      │  │ ESCALATE TO  │                 │
                        │      │  CLOSE node  │  │ HUMAN node   │                 │
                        │      └──────────────┘  └──────────────┘                 │
                        └──────────────────────────┬──────────────────────────────┘
                                                   ▼
                        ┌─────────────────────────────────────────────────────────┐
                        │               ACTION / CHANNEL LAYER                     │
                        │  ┌────────────┐ ┌────────────┐ ┌──────────────────────┐ │
                        │  │ Razorpay   │ │ WhatsApp   │ │ Voice (Hinglish)     │ │
                        │  │ retry/     │ │ (Twilio    │ │ Sarvam STT/TTS +     │ │
                        │  │ mandate/   │ │ Cloud API) │ │ Twilio Voice         │ │
                        │  │ payment    │ │ templates  │ │ (bounded, opted-in)  │ │
                        │  │ link tools │ │            │ │                      │ │
                        │  └────────────┘ └────────────┘ └──────────────────────┘ │
                        └──────────────────────────┬──────────────────────────────┘
                                                   ▼
                        ┌─────────────────────────────────────────────────────────┐
                        │            STATE + AUDIT + EVALUATION LAYER              │
                        │  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌───────────┐ │
                        │  │ Postgres │ │ Audit Log │ │ Langfuse │ │ Batch     │ │
                        │  │ (cases,  │ │ (append-  │ │ tracing  │ │ Evaluator │ │
                        │  │ attempts)│ │ only JSONL│ │          │ │ (₹ metrics)│ │
                        │  └──────────┘ └───────────┘ └──────────┘ └───────────┘ │
                        └──────────────────────────┬──────────────────────────────┘
                                                   ▼
                                          ┌────────────────┐
                                          │  Demo Dashboard │
                                          │  (Next.js)      │
                                          └────────────────┘
```

---

## 3. Component Design

### 3.1 Ingress Layer

| Component | Responsibility | Key details |
|---|---|---|
| **Webhook Receiver** (FastAPI) | Accept Razorpay test-mode webhooks | Verify `X-Razorpay-Signature` with webhook secret; ack within 5s (Razorpay retries with exponential backoff otherwise); enqueue to queue, never process inline |
| **Batch Generator** | Produce synthetic failed-subscription dataset | 100–200 customers × plans on test-mode keys; scripted failure modes: card expired, insufficient funds, mandate revoked, network timeout, wrong UPI handle |
| **Checkout Signal** | Simulate abandonment | Synthetic checkout session events with customer contact + cart value |

Events handled: `payment.failed`, `subscription.pending`, `subscription.charged` (the recovery confirmation), `invoice.paid` (if invoices used).

### 3.2 Case Normalizer + Deduper

- Converts every ingress event into a canonical **Recovery Case**: `{case_id, customer, amount, currency, failure_code, source, state, attempts[]}`
- Idempotency keys: `x-razorpay-event-id` (webhook) and `payment_id` (dedup duplicate failures). Razorpay retries webhooks for 24h — without this, the agent acts twice.
- Enforces one active case per customer per invoice/subscription at a time (no spam).

### 3.3 Agent Core — LangGraph State Machine

**Why LangGraph over CrewAI/ADK:** this workflow is a *state machine with hard gates*, not a role-play team. LangGraph gives:
- explicit graph with conditional edges (retry vs. message vs. voice vs. escalate),
- built-in **checkpointing** → every node transition persisted = the audit trail the judges demand,
- `interrupt()` for **human-in-the-loop approval** before any money-touching or high-risk action,
- model-agnostic (can run Gemini/OpenAI/Claude behind one interface).

**Nodes:**

1. **TRIAGE** — classify case: `recoverable | needs_diagnosis | escalatable | write-off`. Cheap model or rules; sets priority by amount × propensity score.
2. **DIAGNOSE (root cause)** — maps `error_code` / `error_description` from the `payment.failed` payload + customer history to a cause: `card_expired, insufficient_funds, mandate_issue, network_retryable, authentication_failure, unknown`. Output: cause + confidence. Low confidence → escalate, don't guess.
3. **POLICY GATE (hard rules, NOT LLM)** — deterministic checks that can veto any action:
   - Contact window: 9 AM – 9 PM IST only
   - DND / opt-out suppression list
   - Max attempts per case (e.g., ≤ 5) and per channel per day (≤ 2)
   - Amount thresholds: actions above ₹X or mandate changes above ₹Y require human approval
   - Cooling-off: min 24h between customer-facing touches
4. **PLANNER (LLM)** — chooses a bounded intervention from a **fixed action menu** (no free-form actions): e.g., `{retry_payment, refresh_payment_link, whatsapp_reminder, voice_call, pause_and_offer, escalate_human}`. Chooses tone/language (English/Hinglish) and drafts message content grounded in case facts.
5. **EXECUTOR** — runs the chosen action via the channel tools. Every action is **bounded**: retry counts, caps, and idempotency keys are enforced here, not by the LLM.
6. **VERIFIER** — waits/listens for `subscription.charged` / `invoice.paid` / `payment.captured` matching the case, or a timeout. Confirms actual money recovered (this is what makes "measured money recovered" honest).
7. **STOP/CLOSE** — stopping rules: success, max attempts, explicit opt-out, or write-off after N days. Terminal states are explicit, never implicit.
8. **ESCALATE TO HUMAN** — `interrupt()` surfaces the case in the dashboard with full context; human approves/edits/rejects the plan. This is the compliant escalation the track asks for.

**Recovery policies per cause (planner heuristics):**

| Failure cause | First action | Then |
|---|---|---|
| network_retryable | auto-retry (no customer contact) | verify → close or diagnose |
| insufficient_funds | WhatsApp reminder next morning (payday-timed) | retry after confirmation |
| card_expired | payment-link + update-card request | voice call after 48h silence |
| mandate_issue | mandate re-registration link | escalate after 2 failures |
| unknown | escalate to human | — |

### 3.4 Action / Channel Layer

- **Razorpay tools (test mode)**: fetch payment/subscription status, create payment link, retry charge, resume subscription. All calls go through one thin client with retries + idempotency.
- **WhatsApp**: Twilio WhatsApp Business API (India-supported) with pre-approved message templates; a "Pay now" button carries the Razorpay payment link. Fallback: Meta Cloud API direct.
- **Hinglish voice (differentiator)**: Sarvam AI (native code-mixing STT/TTS) over Twilio Voice; bounded script, explicit consent line, DTMF "pay now → send link". Demoable live — this maps directly to the track's "Hinglish voice recovery" direction.
- **Human escalation channel**: dashboard task queue + email/slack-style notification (mock).

### 3.5 State, Audit & Evaluation

- **Postgres**: cases, attempts, channel responses, amounts. Single source of truth.
- **Audit log**: append-only JSONL, one record per agent decision: `{timestamp, case_id, node, input_summary, decision, tool_call, tool_result, policy_checks_passed, model, tokens}`. Never mutated → demo "every money action explainable" by replaying a case's log.
- **Langfuse (or LangSmith)**: LLM call tracing, token cost, latency per case.
- **Batch Evaluator** (the scoring heart): after each synthetic batch run, computes:
  - **Recovered amount / At-risk amount (%)** — the headline metric
  - Recovery rate by failure cause
  - Cost per recovered rupee (LLM tokens + channel cost)
  - Attempts-to-recovery distribution
  - False-action rate (messages sent where no recovery was possible — complaint proxy)
  - Policy violations (must be **zero**; any violation fails the run)

### 3.6 Demo Dashboard (Next.js)

- Case queue with live agent state per case
- One-click case replay from audit log (narrated timeline)
- Batch metrics panel: recovered ₹, rates, costs, policy check = green
- Human approval inbox (approves pending `interrupt()` cases)

---

## 4. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Agent ecosystem, Razorpay SDK |
| API server | FastAPI | Webhook receiver + dashboard API |
| Agent | LangGraph + LangChain | State machine, checkpoints, HITL interrupts |
| LLM | Gemini Flash (cheap loop) + one strong model (GPT-5/Claude) for planner | Cost per recovered rupee is a metric — cheap where possible |
| DB | Postgres (SQLModel) | Durable case state |
| Queue | Redis + arq (or Celery) | Webhook ack must be instant |
| Razorpay | Official Python SDK, test-mode keys | payment.failed / subscription webhooks, payment links, retry |
| WhatsApp | Twilio WhatsApp API (or Meta Cloud API) | India support, templates, delivery receipts |
| Voice | Sarvam AI STT/TTS + Twilio Voice | Native Hinglish code-mixing |
| Tracing | Langfuse | Per-case LLM cost & latency |
| Frontend | Next.js + Tailwind | Demo dashboard |
| Deploy | Docker Compose (single host) | Judges can `docker compose up` |

---

## 5. Data Model (core tables)

- `cases(id, customer_id, subscription_id, amount, currency, source, failure_code, cause, state, priority, created_at, closed_at)`
- `attempts(id, case_id, action_type, channel, payload, result, policy_snapshot, approved_by, created_at)`
- `customers(id, name, phone, lang_pref, opt_out, dnd_flag)`
- `batches(id, started_at, stats_json)` — one row per evaluation run

---

## 6. How this hits the track's bar (explicitly)

| Requirement from the page | Architecture answer |
|---|---|
| "Detects revenue at risk, determines intervention, executes bounded recovery" | Triage → Diagnose → Planner → Executor chain, fixed action menu |
| "Measured money recovered across a batch" | Batch Evaluator: recovered ₹/at-risk ₹ per 100–200 record synthetic batch |
| "Compliant escalation" | Policy Gate (contact windows, DND, caps) + human `interrupt()` above thresholds |
| "Stopping rules" | Explicit terminal states + max attempts + cooling-off enforced in Executor |
| "Audit trail" | LangGraph checkpoints + append-only JSONL decision log, replayable in dashboard |
| "One failure handled gracefully" | Demo a late-authorization case: payment marked failed then authorized later — Verifier reconciles instead of double-charging |

---

## 7. Build order (fits the ~2-week runway to Sep 5)

1. **Day 1–2**: Razorpay test account, plans + subscriptions, webhook receiver with signature verification + idempotency, batch generator
2. **Day 3–5**: LangGraph core (Triage → Diagnose → Policy Gate → Planner → Executor → Verifier → Close), Postgres state, auto-retry path only
3. **Day 6–7**: WhatsApp channel + payment-link tool; first end-to-end recovery on synthetic batch
4. **Day 8–9**: Audit log + Batch Evaluator + metrics dashboard
5. **Day 10**: Human escalation via `interrupt()`
6. **Day 11–12**: Hinglish voice (Sarvam) — the demo wow-moment
7. **Day 13–14**: Polish, failure-handling demo case, 5-min pitch video + README + architecture diagram

---

## 8. Risks & mitigations

- **WhatsApp template approval takes time** → fallback: Twilio sandbox number for demo, mention production path
- **Test mode doesn't auto-fail subscriptions realistically** → Batch Generator drives failures via scripted test cards/mandates
- **LLM doing something unbounded** → Policy Gate + Executor enforce caps in code; LLM can only pick from the action menu
- **Judges test with a tricky case** → keep one "late authorization" and one "opt-out mid-recovery" case ready to replay from audit log
