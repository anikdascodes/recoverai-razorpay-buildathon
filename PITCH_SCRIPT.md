# RecoverAI — 5-Minute Pitch Video Script

> Recording notes: screen recording + talking head for intro/outro. Demo on the live dashboard at `localhost:8000`. Speak the Hinglish line naturally. Total runtime: 5:00.

---

## [0:00–0:30] The problem (Problem Taste)

**[Shot: dashboard KPI cards]**

> "Every month, Indian subscription businesses lose money — not to fraud, but to silence. A card expires. A UPI mandate breaks. A payment fails, the customer never notices, and nobody follows up. The revenue just leaks away.
>
> Collections teams chase these by hand: spreadsheets, cold calls, timing guesswork. It's expensive, inconsistent, and easy to get wrong — contact someone at midnight, or someone who opted out, and you've got a compliance problem on top of a revenue problem.
>
> I built RecoverAI: an agent that detects revenue at risk, diagnoses *why* the payment failed, and executes a bounded, compliant recovery workflow — with humans in control of the big decisions."

---

## [0:30–1:15] The loop (Build Quality)

**[Shot: architecture diagram — show the flow, don't read it]**

> "Here's the loop. Failed payments arrive as Razorpay webhooks — HMAC-verified, deduplicated by event id. Each becomes a Recovery Case.
>
> The agent then walks a state machine built on LangGraph: **triage** sets priority; **diagnose** maps the error code to a root cause — card expired, insufficient funds, mandate broken; a **policy gate** — pure deterministic code, never the LLM — checks contact windows, opt-outs, attempt caps; a **planner** picks exactly one action from a fixed menu; the **executor** runs it through bounded channel tools; and a **verifier** confirms the money actually came back.
>
> Nothing is free-form. Every rupee moved is traceable to a decision, a policy check, and an event."

---

## [1:15–2:30] Live demo — the numbers (Problem Taste + Build Quality)

**[Shot: dashboard, live]**

> "This is a fresh 186-case synthetic batch on Razorpay test-mode APIs. ₹2.2 lakh at risk.
>
> **[Point at KPI cards]** The agent autonomously recovered ₹80,000 — a 36% recovery rate. And here's the number I'm most proud of: **zero policy breaches** across every single customer contact.
>
> **[Point at per-cause bars]** Recovery rate by cause — insufficient funds recovers best at 43%, because the timing matters: payday reminders work. Network failures auto-retry with zero customer contact — the customer never even knows.
>
> **[Click a case → decision trail]** Every case has a full replay — triage, diagnosis with confidence, each policy check, the planned action, the outcome. This is the audit trail. Every money action is explainable after the fact."

---

## [2:30–3:30] Humans in control + the graceful failure (Failure Recovery)

**[Shot: Human Approval inbox]**

> "Big decisions stay human. Any case above ₹2,000 lands in this approval inbox before the agent contacts the customer.
>
> **[Approve a case live]** Approving unlocks *only* the amount gate — compliance gates still apply. The reminder fires, and… **[point]** the money recovers, live.
>
> One more thing — failures. **[Terminal: run `python -m app.demo.late_authorization`]** Here's my favorite bug class: a payment fails, the agent exhausts every attempt, writes the case off. Four days later, the issuing bank authorizes the original charge anyway. The reconciler pulls the case out of written-off, credits the money, and guarantees no further customer contact. Duplicate events are idempotent — no double-counting.
>
> And when the LLM itself rate-limits — which happened mid-batch — diagnosis falls back to a deterministic error-code mapper. 146 of 186 cases ran on the fallback. Zero misclassifications. The system degrades gracefully instead of breaking."

---

## [3:30–4:15] AI judgment (AI Judgment)

**[Shot: back to talking head or code view of `nodes.py` policy gate]**

> "My design philosophy: the LLM is a *component*, not the system.
>
> The policy gate is deterministic Python — compliance rules must never be a prompt. The planner picks from a fixed menu with a fallback action — an LLM outage means a dumber choice, never an unsafe one. The verifier can't decide recovery at all — only a signed money-moved event, flowing through the same HMAC-verified ingest path as real Razorpay traffic, can mark a case recovered.
>
> So the LLM does what it's good at — judgment calls on channel and message — inside rails it cannot leave."

---

## [4:15–5:00] Real vs simulated + close

**[Shot: the "Real vs simulated" table in the README]**

> "Full honesty about what's simulated: the webhook mechanics, Razorpay test-mode payment links, LLM calls, policy gates, audit trail and human inbox are all real plumbing. Synthetic customers can't actually pay, so a world simulator plays the customer — and it plugs in at exactly one point: it emits the *same signed webhook* Razorpay would. WhatsApp runs through Twilio when credentials exist, and is honestly labeled `simulated` when they don't.
>
> What's next: real Twilio WhatsApp templates, Hinglish voice recovery on Sarvam, and a cost-per-recovered-rupee metric.
>
> RecoverAI — every rupee measured, every action explainable, every escalation compliant. The code is public, the audit log is replayable, and the demo takes one command. Thank you."

---

## Shot checklist

- [ ] Fresh batch run before recording (`python -m app.generator.batch --customers 120` then `python -m app.agent.run_batch`) so dashboard numbers are live
- [ ] One ≥₹2,000 case queued in the approval inbox for the live approve demo
- [ ] `python -m app.demo.late_authorization` rehearsed, terminal font large
- [ ] README "Real vs simulated" table on screen at the end
- [ ] Mic check: the Hinglish consent line reads naturally
