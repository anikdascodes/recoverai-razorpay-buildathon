"""Demo: late-authorization reconciliation.

Scenario (the track's "one failure handled gracefully"):
1. A payment fails -> the agent works the case -> attempts exhausted ->
   case is written off (terminal state for agent actions).
2. Days later the issuing bank actually authorizes the original charge and
   Razorpay emits ``payment.captured``.
3. The reconciler pulls the case out of WRITTEN_OFF -> RECOVERED, credits the
   money, audits the exception, and guarantees no further customer contact.

Run:  python -m app.demo.late_authorization
"""

import os

from sqlalchemy import select

from app.agent.audit import audit
from app.db import SessionLocal, init_db
from app.models import Case, CaseState, Customer, FailureCause
from app.worldsim import late_authorization


def main() -> None:
    init_db()
    with SessionLocal() as db:
        cust = Customer(name="Late Auth Demo", phone="+919000000999", email="late@example.com")
        db.add(cust)
        db.flush()
        case = Case(
            customer_id=cust.id,
            subscription_id="sub_LATEAUTH_DEMO",
            amount=499_00,
            source="razorpay",
            source_ref="pay_LATEAUTH_DEMO",
            failure_code="GATEWAY_ERROR",
            failure_reason="Gateway error: timeout at issuing bank",
            cause=FailureCause.NETWORK_RETRYABLE,
            state=CaseState.WRITTEN_OFF,  # agent already exhausted attempts
            attempts_count=5,
            priority=3,
        )
        db.add(case)
        db.commit()
        print(f"seeded case #{case.id} in state=written_off (attempts exhausted)")

    print("issuing bank authorizes the original charge 4 days later...")
    result = late_authorization(case.source_ref)
    print(f"webhook ingested: {result}")

    with SessionLocal() as db:
        fresh = db.get(Case, case.id)
        print(f"case #{fresh.id} state={fresh.state.value} recovered=Rs {fresh.recovered_amount / 100:.0f}")
        assert fresh.state == CaseState.RECOVERED

    print("\naudit trail for this case:")
    
    for line in Path(os.getenv("AUDIT_FILE", "audit.jsonl")).read_text(encoding="utf-8").splitlines():
        rec = __import__("json").loads(line)
        if rec.get("case_id") == case.id:
            print(f"  {rec['ts'][:19]}  {rec['node']:<12} {rec.get('decision', '')}")
            if rec.get("reason"):
                print(f"               reason: {rec['reason']}")

    # double-fire the same scenario: reconciliation must be idempotent
    late_authorization(case.source_ref)
    with SessionLocal() as db:
        fresh = db.get(Case, case.id)
        assert fresh.state == CaseState.RECOVERED
        assert fresh.recovered_amount == fresh.amount, "double-counted!"
    print("\nidempotency check: duplicate captured event did not double-count. OK")
    audit({"case_id": case.id, "node": "demo", "decision": "late_authorization_demo_complete"})


if __name__ == "__main__":
    main()
