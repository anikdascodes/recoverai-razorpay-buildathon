import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.agent.audit import audit
from app.agent.llm import LLMError, chat
from app.agent.state import AgentState
from app.channels.razorpay_client import RazorpayClient
from app.channels.voice import build_script, place_call
from app.channels.whatsapp import send_whatsapp
from app.config import get_settings
from app.models import Attempt, Case, CaseState, Customer, FailureCause, utcnow
from app.normalizer import CAUSE_BY_ERROR
from app.state_machine import transition
from app.worldsim import reference_id_for, settle_action

MAX_ATTEMPTS = 5
HUMAN_APPROVAL_THRESHOLD_PAISE = 200_000
IST = timezone(timedelta(hours=5, minutes=30))

ACTION_MENU = {
    FailureCause.NETWORK_RETRYABLE: ["auto_retry"],
    FailureCause.INSUFFICIENT_FUNDS: ["auto_retry", "whatsapp_reminder", "pause_and_offer"],
    FailureCause.CARD_EXPIRED: ["payment_link_update_card", "whatsapp_reminder", "voice_call"],
    FailureCause.MANDATE_ISSUE: ["mandate_relink", "voice_call"],
    FailureCause.AUTHENTICATION_FAILURE: ["whatsapp_reminder", "voice_call"],
    FailureCause.UNKNOWN: ["whatsapp_reminder", "voice_call"],
}
CUSTOMER_FACING = {"whatsapp_reminder", "payment_link_update_card", "voice_call", "pause_and_offer", "mandate_relink"}
LINK_ACTIONS = {"whatsapp_reminder", "payment_link_update_card", "mandate_relink", "pause_and_offer"}


def _load_case(db, case_id: int) -> tuple[Case, Customer]:
    case = db.get(Case, case_id)
    customer = db.get(Customer, case.customer_id)
    return case, customer


def _base_state(case: Case, customer: Customer) -> AgentState:
    last_action = ""
    with SessionLocalSafe() as db:
        prev = db.scalar(
            select(Attempt).where(Attempt.case_id == case.id).order_by(Attempt.id.desc())
        )
        if prev is not None:
            last_action = prev.action_type
    return {
        "case_id": case.id,
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "lang_pref": customer.lang_pref,
            "opt_out": customer.opt_out,
            "dnd_flag": customer.dnd_flag,
        },
        "amount_paise": case.amount,
        "source": case.source,
        "subscription_id": case.subscription_id,
        "failure_code": case.failure_code,
        "failure_reason": case.failure_reason,
        "attempts": case.attempts_count,
        "round_no": case.attempts_count,
        "last_action": last_action,
    }


def triage(state: AgentState) -> dict:
    with SessionLocalSafe() as db:
        case, _ = _load_case(db, state["case_id"])
        if case.state == CaseState.OPEN:
            case.state = CaseState.DIAGNOSING
            db.commit()
    audit({"case_id": state["case_id"], "node": "triage", "decision": "route_to_diagnose"})
    return {}


def diagnose(state: AgentState) -> dict:
    prompt = (
        'You are a payments recovery analyst for an Indian fintech. Classify the ROOT CAUSE of this failed '
        'subscription payment and reply ONLY with JSON: {"cause": one of [card_expired, insufficient_funds, '
        'mandate_issue, network_retryable, authentication_failure, unknown], "confidence": 0.0-1.0, "note": '
        '"one short sentence"}\n\n'
        f'error_code: {state["failure_code"]}\n'
        f'error_description: {state["failure_reason"]}\n'
        f'amount_paise: {state["amount_paise"]}\n'
        f'previous_attempts: {state["attempts"]}'
    )
    try:
        content, usage = chat([{"role": "user", "content": prompt}], json_mode=True)
        data = json.loads(content)
        cause = data["cause"]
        confidence = float(data["confidence"])
        note = data.get("note", "")[:200]
        valid = cause in [c.value for c in FailureCause]
    except (LLMError, json.JSONDecodeError, KeyError, ValueError):
        valid = False

    if not valid:
        mapped = CAUSE_BY_ERROR.get(state["failure_code"], FailureCause.UNKNOWN)
        cause, confidence, note = mapped.value, 0.6, "rule-based fallback"
        usage = {}
    audit({
        "case_id": state["case_id"], "node": "diagnose",
        "decision": cause, "confidence": confidence, "note": note,
        "model": get_settings().agent_model, "tokens": usage.get("total_tokens"),
    })
    return {"cause": cause, "confidence": confidence, "diag_note": note}


def policy_gate(state: AgentState) -> dict:
    now_ist = datetime.now(IST)
    in_window = 9 <= now_ist.hour < 21
    menu = list(ACTION_MENU.get(FailureCause(state["cause"]), ACTION_MENU[FailureCause.UNKNOWN]))
    violations: list[str] = []
    allowed: list[str] = []

    cust = state["customer"]
    for action in menu:
        blocked = False
        if action in CUSTOMER_FACING:
            if not in_window:
                violations.append(f"{action}: outside 9-21 IST contact window")
                blocked = True
            if cust["opt_out"]:
                violations.append(f"{action}: customer opted out")
                blocked = True
            if cust["dnd_flag"]:
                violations.append(f"{action}: DND flag set")
                blocked = True
            if state["attempts"] >= MAX_ATTEMPTS:
                violations.append(f"{action}: max attempts reached")
                blocked = True
        if not blocked:
            allowed.append(action)

    needs_human = (not state.get("human_approved")) and state["amount_paise"] >= HUMAN_APPROVAL_THRESHOLD_PAISE
    audit({
        "case_id": state["case_id"], "node": "policy_gate",
        "allowed": allowed, "violations": violations, "needs_human": needs_human,
    })
    return {
        "allowed_actions": allowed,
        "violations": violations,
        "needs_human": needs_human,
    }


def planner(state: AgentState) -> dict:
    menu = state["allowed_actions"]
    cust = state["customer"]
    lang = cust.get("lang_pref", "en")
    prompt = (
        'You are a recovery planner. Pick ONE action from the menu and draft the message if the action is '
        'customer-facing. Rules: message must be under 300 chars, include the placeholder {link} where the '
        'payment link goes, never promise refunds or discounts, tone friendly respectful Indian. If a previous '
        'action already failed, prefer a DIFFERENT channel this time.\n'
        f'Reply ONLY JSON: {{"action": one of {json.dumps(menu)}, "message": "..." (empty string if not '
        f'customer-facing)}}\n\n'
        f'customer_language_pref: {lang}\n'
        f'root_cause: {state["cause"]} ({state["confidence"]:.2f})\n'
        f'diagnosis_note: {state["diag_note"]}\n'
        f'amount_rupees: {state["amount_paise"] / 100:.0f}\n'
        f'attempts_so_far: {state["attempts"]}\n'
        f'previous_failed_action: {state.get("last_action", "none")}'
    )
    fallback_action = menu[0]
    try:
        content, usage = chat([{"role": "user", "content": prompt}], json_mode=True)
        data = json.loads(content)
        action = data["action"]
        message = str(data.get("message", ""))[:400]
        if action not in menu:
            action, message = fallback_action, ""
    except (LLMError, json.JSONDecodeError, KeyError):
        action, message, usage = fallback_action, "", {}
    channel = {
        "auto_retry": "razorpay", "whatsapp_reminder": "whatsapp",
        "payment_link_update_card": "whatsapp", "voice_call": "voice",
        "mandate_relink": "whatsapp", "pause_and_offer": "whatsapp",
    }.get(action, "internal")
    audit({
        "case_id": state["case_id"], "node": "planner",
        "decision": action, "channel": channel, "message": message[:120],
        "model": get_settings().agent_model, "tokens": usage.get("total_tokens"),
    })
    return {"action": action, "channel": channel, "message": message}


def executor(state: AgentState) -> dict:
    action = state["action"]
    result: dict = {"action": action}
    link_url = ""
    round_no = state.get("round_no", 0)

    with SessionLocalSafe() as db:
        case, _ = _load_case(db, state["case_id"])
        case.state = transition(case.state, CaseState.ACTING)

        if action in LINK_ACTIONS:
            s = get_settings()
            if s.has_live_keys:
                try:
                    rc = RazorpayClient()
                    pl = rc.create_payment_link(
                        amount=state["amount_paise"],
                        customer={"name": state["customer"]["name"], "phone": state["customer"]["phone"],
                                  "email": ""},
                        description=f"Recovery payment for case #{state['case_id']}",
                        reference_id=reference_id_for(state["case_id"], round_no),
                    )
                    rc.close()
                    link_url = pl.get("short_url", "")
                    result["payment_link_id"] = pl.get("id")
                    result["mode"] = "live"
                except Exception as e:
                    result["link_error"] = str(e)[:120]
            if not link_url:
                link_url = f"https://rzp.io/i/synthetic-case{state['case_id']}r{round_no}"
                result.setdefault("mode", "simulated")
            result["link"] = link_url

            if action == "voice_call":
                script = state["message"] or build_script(
                    state["customer"]["name"], state["amount_paise"] / 100,
                    state["customer"].get("lang_pref", "en"), link_url,
                )
                result["voice"] = place_call(state["customer"]["phone"], script)
                if state["message"]:
                    result["script_preview"] = state["message"].replace("{link}", link_url)
            else:
                body = state["message"].replace("{link}", link_url) if state["message"] else \
                    f"Your payment of Rs {state['amount_paise'] / 100:.0f} failed. Pay securely: {link_url}"
                result["delivery"] = send_whatsapp(state["customer"]["phone"], body)
                result["message_preview"] = body

        elif action == "auto_retry":
            if state["source"] == "synthetic":
                result["mode"] = "simulated"
            else:
                try:
                    rc = RazorpayClient()
                    r = rc.retry_subscription_charge(state["subscription_id"], state["amount_paise"])
                    rc.close()
                    result.update({"mode": "live", **r})
                except Exception as e:
                    result.update({"mode": "live", "error": str(e)[:120]})

        db.add(Attempt(
            case_id=case.id, action_type=action, channel=state["channel"],
            payload={"message": state["message"], "link": link_url}, result=result,
        ))
        case.attempts_count += 1
        case.state = transition(case.state, CaseState.AWAITING_PAYMENT)
        db.commit()
        result["attempts_now"] = case.attempts_count

    # The world responds AFTER the action is on record. For synthetic cases
    # the world simulator emits a signed money-moved event through the same
    # ingest path as live traffic; live cases are confirmed by real webhooks.
    if state["source"] == "synthetic":
        with SessionLocalSafe() as db:
            case, _ = _load_case(db, state["case_id"])
            result["worldsim"] = settle_action(case, action, round_no)

    audit({"case_id": state["case_id"], "node": "executor", "decision": action, "result": result})
    return {"exec_result": result}


def verifier(state: AgentState) -> dict:
    """Recovery is only ever confirmed by a money-moved event
    (subscription.charged / payment_link.paid / payment.captured / invoice.paid)
    flowing through the signed ingest path and matched to this case by the
    normalizer. The verifier reads that outcome; it never decides it."""
    with SessionLocalSafe() as db:
        case, _ = _load_case(db, state["case_id"])
        recovered = case.state == CaseState.RECOVERED
        if recovered:
            confirmed_at = case.closed_at.isoformat() if case.closed_at else None
        else:
            confirmed_at = None

    audit({
        "case_id": state["case_id"], "node": "verifier",
        "decision": "recovered_confirmed_by_event" if recovered else "not_yet",
    })
    return {"recovered": recovered, "confirmed_at": confirmed_at}


def escalate(state: AgentState) -> dict:
    with SessionLocalSafe() as db:
        case, _ = _load_case(db, state["case_id"])
        if case.state not in (CaseState.RECOVERED, CaseState.WRITTEN_OFF):
            case.state = CaseState.ESCALATED
        db.commit()
    summary = (
        f"Case #{state['case_id']}: {state['failure_code']} | cause={state.get('cause', '?')} "
        f"conf={state.get('confidence', 0):.2f} | attempts={state['attempts']} "
        f"| violations={len(state.get('violations', []))}"
    )
    audit({"case_id": state["case_id"], "node": "escalate", "decision": "human_review", "summary": summary})
    return {"stop_reason": "escalated_to_human"}


def write_off(state: AgentState) -> dict:
    with SessionLocalSafe() as db:
        case, _ = _load_case(db, state["case_id"])
        case.state = CaseState.WRITTEN_OFF
        case.closed_at = utcnow()
        db.commit()
    audit({
        "case_id": state["case_id"], "node": "write_off", "decision": "terminal",
        "reason": "; ".join(state.get("violations", [])) or "stopping rules reached",
    })
    return {"stop_reason": "written_off"}


def SessionLocalSafe():
    from app.db import SessionLocal

    return SessionLocal()


def route_after_diagnose(state: AgentState) -> str:
    return "policy_gate"


def route_after_policy(state: AgentState) -> str:
    if state.get("needs_human"):
        return "escalate"
    if not state.get("allowed_actions"):
        v = " ".join(state.get("violations", []))
        # Opted-out / DND customers can never be contacted compliantly. No
        # amount of human approval changes that — escalation would bounce the
        # case back and forth forever. Write off and stop.
        if "opted out" in v or "DND" in v:
            return "write_off"
        if "max attempts" in v:
            return "write_off"
        return "defer"
    return "planner"


def defer(state: AgentState) -> dict:
    with SessionLocalSafe() as db:
        case, _ = _load_case(db, state["case_id"])
        if case.state == CaseState.DIAGNOSING:
            case.state = transition(case.state, CaseState.AWAITING_PAYMENT)
        db.commit()
    audit({"case_id": state["case_id"], "node": "defer", "decision": "wait_for_contact_window"})
    return {"stop_reason": "deferred_contact_window"}


def route_after_verify(state: AgentState) -> str:
    if state.get("recovered"):
        return "__end__"
    if state.get("exec_result", {}).get("attempts_now", 0) >= MAX_ATTEMPTS:
        return "write_off"
    return "__end__"
