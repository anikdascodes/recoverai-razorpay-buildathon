import os

os.environ["DATABASE_URL"] = "sqlite:///./test_day2.db"

from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.generator.batch import generate_batch
from app.main import app
from app.models import Case, CaseState
from app.state_machine import IllegalTransition, transition


def run() -> None:
    init_db()
    generate_batch(50)

    with SessionLocal() as db:
        case = db.query(Case).first()

        transition(case.state, CaseState.DIAGNOSING)
        case.state = CaseState.DIAGNOSING
        transition(case.state, CaseState.ACTING)
        case.state = CaseState.ACTING
        transition(case.state, CaseState.AWAITING_PAYMENT)
        case.state = CaseState.AWAITING_PAYMENT
        transition(case.state, CaseState.RECOVERED)
        case.state = CaseState.RECOVERED
        case.recovered_amount = case.amount
        db.commit()

        try:
            transition(CaseState.RECOVERED, CaseState.ACTING)
            raise AssertionError("should have raised")
        except IllegalTransition:
            pass

    client = TestClient(app)
    r = client.get("/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["cases"]["total"] > 0
    assert data["money"]["at_risk_paise"] > 0

    print("STATE MACHINE: legal path ok, illegal RECOVERED->ACTING rejected")
    print("STATS:", {
        "cases": data["cases"],
        "recovery_rate_pct": data["money"]["recovery_rate_pct"],
        "at_risk_rs": data["money"]["at_risk_rupees"],
    })


if __name__ == "__main__":
    run()
