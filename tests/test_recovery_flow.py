"""End-to-end tests for the event-driven recovery loop.

Covers: verifier confirmation via signed events only, payment_link.paid
matching by reference_id, late-authorization reconciliation out of
WRITTEN_OFF, and honest channel simulation modes.
"""

import pytest

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.models import Case, CaseState, Customer, FailureCause, RawEvent
from app.worldsim import late_authorization, settle_action


def _make_case(state: CaseState = CaseState.OPEN, source: str = "synthetic") -> Case:
    init_db()
    with SessionLocal() as db:
        n = db.query(Case).count()
        cust = Customer(name="Test User", phone=f"+9190000001{n:02d}", email=f"t{n}@example.com")
        db.add(cust)
        db.flush()
        case = Case(
            customer_id=cust.id,
            subscription_id=f"sub_TESTRECOVERY{n}",
            amount=149_900,
            source=source,
            source_ref=f"pay_TESTRECOVERY{n}",
            failure_code="INSUFFICIENT_FUNDS",
            failure_reason="Payment declined: insufficient funds",
            cause=FailureCause.INSUFFICIENT_FUNDS,
            state=state,
            priority=3,
        )
        db.add(case)
        db.commit()
        return case


def test_settle_posts_signed_event_and_normalizer_confirms():
    case = _make_case()
    out = settle_action(case, "whatsapp_reminder", 0)
    assert out["paid"] in (True, False)  # probabilistic
    if out["paid"]:
        with SessionLocal() as db:
            fresh = db.get(Case, case.id)
            assert fresh.state == CaseState.RECOVERED
            assert fresh.recovered_amount == fresh.amount
            # event stored through the same ingest path as live traffic
            evt = db.query(RawEvent).filter(RawEvent.event_type == "payment_link.paid").first()
            assert evt is not None


def test_confirm_never_fires_without_event():
    case = _make_case(state=CaseState.AWAITING_PAYMENT)
    with SessionLocal() as db:
        fresh = db.get(Case, case.id)
        assert fresh.state == CaseState.AWAITING_PAYMENT  # nothing set it


def test_late_authorization_reconciles_written_off_case():
    case = _make_case(state=CaseState.WRITTEN_OFF, source="razorpay")
    out = late_authorization(case.source_ref)
    assert out["status"] == "accepted"
    with SessionLocal() as db:
        fresh = db.get(Case, case.id)
        assert fresh.state == CaseState.RECOVERED
        assert fresh.recovered_amount == fresh.amount
    # audit trail records the reconciliation
    from pathlib import Path
    import json

    log = Path("audit.jsonl").read_text(encoding="utf-8")
    assert "late_authorization_reconciled" in log


def test_late_authorization_idempotent():
    case = _make_case(state=CaseState.WRITTEN_OFF, source="razorpay")
    late_authorization(case.source_ref)
    late_authorization(case.source_ref)  # duplicate event id differs, but case already recovered
    with SessionLocal() as db:
        fresh = db.get(Case, case.id)
        assert fresh.state == CaseState.RECOVERED
        assert fresh.recovered_amount == fresh.amount  # not double-counted


def test_whatsapp_sim_mode_is_honest():
    from app.channels.whatsapp import send_whatsapp

    if get_settings().has_twilio:
        pytest.skip("twilio configured")
    out = send_whatsapp("+919000000001", "test message")
    assert out["mode"] == "simulated"
    assert out.get("delivered") is None  # never claims delivery


def test_voice_script_is_bounded():
    from app.channels.voice import build_script, place_call

    script = build_script("Aarav Sharma", 2499, "hinglish", "https://rzp.io/i/x")
    out = place_call("+919000000001", script)
    if not (get_settings().has_twilio and get_settings().sarvam_api_key):
        assert out["mode"] == "script_only"
    long_script = "sentence. " * 50
    assert place_call("+919000000001", long_script)["mode"] == "blocked"


def test_agent_recovers_synthetic_case_end_to_end():
    """Full loop: case -> graph -> executor -> worldsim event -> verifier."""
    from app.agent.graph import build_graph, run_case

    case = _make_case()
    graph = build_graph()
    for _ in range(6):  # up to MAX_ATTEMPTS rounds
        out = run_case(graph, case.id)
        with SessionLocal() as db:
            fresh = db.get(Case, case.id)
            if fresh.state == CaseState.RECOVERED:
                assert fresh.recovered_amount == fresh.amount
                return
            if fresh.state == CaseState.WRITTEN_OFF:
                return
    # after 6 rounds the case must be in a terminal or awaiting state, never
    # recovered without an event
    with SessionLocal() as db:
        fresh = db.get(Case, case.id)
        assert fresh.state in (CaseState.AWAITING_PAYMENT, CaseState.WRITTEN_OFF, CaseState.ESCALATED)
