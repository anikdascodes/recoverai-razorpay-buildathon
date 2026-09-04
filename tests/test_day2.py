from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.generator.batch import generate_batch
from app.main import app
from app.models import Case, CaseState, Customer, FailureCause
from app.state_machine import IllegalTransition, transition


def _fresh_case() -> Case:
    init_db()
    with SessionLocal() as db:
        cust = Customer(name="SM Test", phone="+919000000901", email="sm@example.com")
        db.add(cust)
        db.flush()
        case = Case(
            customer_id=cust.id,
            subscription_id="sub_SM1",
            amount=149_900,
            source="synthetic",
            source_ref="pay_SM1",
            failure_code="INSUFFICIENT_FUNDS",
            failure_reason="declined",
            cause=FailureCause.INSUFFICIENT_FUNDS,
            state=CaseState.OPEN,
            priority=3,
        )
        db.add(case)
        db.commit()
        return case


def test_legal_path_and_illegal_rejection():
    case = _fresh_case()
    with SessionLocal() as db:
        c = db.get(Case, case.id)

        c.state = transition(c.state, CaseState.DIAGNOSING)
        c.state = transition(c.state, CaseState.ACTING)
        c.state = transition(c.state, CaseState.AWAITING_PAYMENT)
        c.state = transition(c.state, CaseState.RECOVERED)
        c.recovered_amount = c.amount
        db.commit()

        try:
            transition(CaseState.RECOVERED, CaseState.ACTING)
            raise AssertionError("should have raised")
        except IllegalTransition:
            pass

        # written-off cases can only exit via the reconciler, never directly
        try:
            transition(CaseState.WRITTEN_OFF, CaseState.ACTING)
            raise AssertionError("should have raised")
        except IllegalTransition:
            pass


def test_stats_endpoint():
    init_db()
    client = TestClient(app)
    r = client.get("/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["cases"]["total"] > 0
    assert data["money"]["at_risk_paise"] > 0


def test_generate_batch_seeds_cases():
    init_db()
    stats = generate_batch(5)
    assert stats["cases"] > 0
    with SessionLocal() as db:
        assert db.query(Case).filter(Case.source == "synthetic").count() >= stats["cases"]
