from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.audit import audit
from app.models import Case, CaseState, Customer, FailureCause, RawEvent, utcnow

CAUSE_BY_ERROR = {
    "CARD_IS_EXPIRED": FailureCause.CARD_EXPIRED,
    "GATEWAY_ERROR": FailureCause.NETWORK_RETRYABLE,
    "NETWORK_ERROR": FailureCause.NETWORK_RETRYABLE,
    "INSUFFICIENT_FUNDS": FailureCause.INSUFFICIENT_FUNDS,
    "PAYMENT_AUTHENTICATION_FAILED": FailureCause.AUTHENTICATION_FAILURE,
    "MANDATE_REVOKED": FailureCause.MANDATE_ISSUE,
    "BAD_REQUEST_ERROR": FailureCause.UNKNOWN,
}

# Plausibility ceiling for a single subscription payment: Rs 10,00,000.
# Anything above is treated as a malformed/hostile event, not revenue at risk.
MAX_PLAUSIBLE_AMOUNT_PAISE = 100_000_00


def _get_or_create_customer(db: Session, entity: dict) -> Customer:
    contact = entity.get("contact") or entity.get("email") or "unknown"
    customer = db.scalar(select(Customer).where(Customer.phone == str(contact)))
    if customer is None:
        customer = Customer(
            name=entity.get("email", "").split("@")[0] or "unknown",
            phone=str(contact),
            email=entity.get("email", "") or "",
        )
        db.add(customer)
        db.flush()
    return customer


def normalize_event(db: Session, raw: RawEvent) -> int | None:
    payload = raw.payload.get("payload", {})
    event_type = raw.event_type

    if event_type == "payment.failed":
        payment = payload.get("payment", {}).get("entity", {})
        source_ref = payment.get("id")
        if not source_ref:
            return None
        amount = int(payment.get("amount") or 0)
        if amount <= 0 or amount > MAX_PLAUSIBLE_AMOUNT_PAISE:
            audit({
                "case_id": None, "node": "normalizer", "decision": "event_rejected",
                "reason": f"implausible amount {amount} on payment {source_ref}; case not created",
            })
            return None
        existing = db.scalar(select(Case).where(Case.source == "razorpay", Case.source_ref == source_ref))
        if existing:
            return existing.id
        notes = payment.get("notes") or {}
        customer_id = notes.get("internal_customer_id")
        if customer_id is None:
            customer = _get_or_create_customer(db, payment)
            customer_id = customer.id
        error_code = payment.get("error_code") or ""
        case = Case(
            customer_id=customer_id,
            subscription_id=(payment.get("invoice_id") or payment.get("order_id") or ""),
            amount=amount,
            currency=payment.get("currency", "INR"),
            source="razorpay",
            source_ref=source_ref,
            failure_code=error_code,
            failure_reason=payment.get("error_description") or "",
            cause=CAUSE_BY_ERROR.get(error_code, FailureCause.UNKNOWN),
            state=CaseState.OPEN,
            priority=_priority(amount),
        )
        db.add(case)
        db.flush()
        return case.id

    if event_type in {"subscription.charged", "invoice.paid"}:
        entity = payload.get("subscription", {}).get("entity") or payload.get("invoice", {}).get("entity") or {}
        sub_ref = entity.get("id", "")
        case = db.scalar(
            select(Case).where(Case.subscription_id == sub_ref).order_by(Case.id.desc())
        )
        if case:
            return _confirm_recovery(db, case, event_type)

    if event_type == "payment_link.paid":
        link = payload.get("payment_link", {}).get("entity", {})
        ref = link.get("reference_id", "")  # recoverai_case_{id}_r{n}
        case = None
        if ref.startswith("recoverai_case_"):
            case_id = int(ref.split("_")[2])
            case = db.get(Case, case_id)
        if case:
            return _confirm_recovery(db, case, event_type)

    if event_type == "payment.captured":
        payment = payload.get("payment", {}).get("entity", {})
        pay_ref = payment.get("id", "")
        case = db.scalar(select(Case).where(Case.source_ref == pay_ref))
        if case:
            return _confirm_recovery(db, case, event_type, late=case.state == CaseState.WRITTEN_OFF)

    return None


def _confirm_recovery(db: Session, case: Case, event_type: str, late: bool = False) -> int:
    """Mark a case recovered from a money-moved event. The only path that may
    pull a case out of WRITTEN_OFF is a genuine late authorization — audited
    as such, and never reachable through agent actions."""
    if case.state == CaseState.RECOVERED:
        return case.id
    case.state = CaseState.RECOVERED
    case.recovered_amount = case.amount
    case.closed_at = utcnow()
    db.commit()
    if late:
        audit({
            "case_id": case.id, "node": "reconciler", "event": event_type,
            "decision": "late_authorization_reconciled",
            "reason": "payment captured by issuing bank after write-off; recovered, no further customer contact",
        })
    else:
        audit({
            "case_id": case.id, "node": "verifier", "event": event_type,
            "decision": "recovered_confirmed_by_event",
        })
    return case.id


def _priority(amount: int) -> int:
    if amount >= 500_000:
        return 1
    if amount >= 100_000:
        return 2
    return 3
