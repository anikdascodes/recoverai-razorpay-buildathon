import argparse
import os
import random
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select

from app.db import SessionLocal, init_db
from app.models import Case, CaseState, Customer, FailureCause, utcnow

AUDIT_FILE = Path(os.getenv("AUDIT_FILE", "audit.jsonl"))

FIRST_NAMES = [
    "Aarav", "Diya", "Rohan", "Priya", "Kabir", "Ananya", "Vikram", "Meera",
    "Arjun", "Sneha", "Ishaan", "Kavya", "Rahul", "Pooja", "Dev", "Nisha",
]
LAST_NAMES = ["Sharma", "Patel", "Reddy", "Iyer", "Gupta", "Singh", "Nair", "Das"]


def _rotate_audit_if_fresh_db() -> None:
    """A fresh batch means a fresh case-id space. The append-only audit log
    from a previous DB generation would otherwise leak ghost events into the
    new run's case replays, so archive it first."""
    with SessionLocal() as db:
        existing = db.scalar(select(func.count(Case.id))) or 0
    audit_file = AUDIT_FILE
    if existing == 0 and audit_file.exists() and audit_file.stat().st_size > 0:
        archive = audit_file.with_name(f"audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl")
        audit_file.rename(archive)
        print(f"archived previous audit log -> {archive.name}")

FAILURE_MIX = [
    (FailureCause.INSUFFICIENT_FUNDS, 0.30, "INSUFFICIENT_FUNDS", "Payment declined: insufficient funds"),
    (FailureCause.CARD_EXPIRED, 0.22, "CARD_IS_EXPIRED", "The card has expired"),
    (FailureCause.NETWORK_RETRYABLE, 0.20, "GATEWAY_ERROR", "Gateway error: timeout at issuing bank"),
    (FailureCause.MANDATE_ISSUE, 0.15, "MANDATE_REVOKED", "UPI mandate revoked by customer"),
    (FailureCause.AUTHENTICATION_FAILURE, 0.08, "PAYMENT_AUTHENTICATION_FAILED", "3DS authentication failed"),
    (FailureCause.UNKNOWN, 0.05, "BAD_REQUEST_ERROR", "Unknown failure"),
]

PLANS = [19900, 49900, 99900, 149900, 249900]


def _pick_failure() -> tuple[FailureCause, str, str]:
    roll = random.random()
    acc = 0.0
    for cause, weight, code, reason in FAILURE_MIX:
        acc += weight
        if roll <= acc:
            return cause, code, reason
    return FAILURE_MIX[-1][0], FAILURE_MIX[-1][2], FAILURE_MIX[-1][3]


def generate_batch(n_customers: int = 120) -> dict:
    init_db()
    _rotate_audit_if_fresh_db()
    created_cases = 0
    total_at_risk = 0

    with SessionLocal() as db:
        for _ in range(n_customers):
            name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
            phone = f"+919{random.randint(100000000, 999999999)}"
            lang = random.choice(["en", "hi", "hinglish"])
            opt_out = random.random() < 0.05
            customer = Customer(name=name, phone=phone, email=f"{name.split()[0].lower()}{random.randint(1, 99)}@example.com", lang_pref=lang, opt_out=opt_out)
            db.add(customer)
            db.flush()

            n_failures = random.choices([1, 2, 3], weights=[0.6, 0.3, 0.1])[0]
            for i in range(n_failures):
                amount = random.choice(PLANS)
                cause, code, reason = _pick_failure()
                case = Case(
                    customer_id=customer.id,
                    subscription_id=f"sub_SYNTH{random.randint(10**8, 10**9 - 1)}",
                    amount=amount,
                    source="synthetic",
                    source_ref=f"pay_SYNTH{random.randint(10**10, 10**11 - 1)}",
                    failure_code=code,
                    failure_reason=reason,
                    cause=cause,
                    state=CaseState.OPEN,
                    priority=3,
                )
                db.add(case)
                created_cases += 1
                total_at_risk += amount
        db.commit()

        stats = {
            "customers": n_customers,
            "cases": created_cases,
            "at_risk_paise": total_at_risk,
        }
        by_cause = dict(
            db.execute(select(Case.cause, func.count(Case.id)).group_by(Case.cause)).all()
        )
    stats["by_cause"] = {c.value if hasattr(c, "value") else str(c): n for c, n in by_cause.items()}
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--customers", type=int, default=120)
    args = parser.parse_args()
    print(generate_batch(args.customers))
