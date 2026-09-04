import hashlib
import hmac

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.main import app
from app.models import Case, RawEvent
def sign(body: bytes) -> tuple[str, str]:
    secret = get_settings().rzp_webhook_secret
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return sig, "evt_test_001"


def make_event(payment_id: str = "pay_TEST123") -> bytes:
    return (
        b'{"event":"payment.failed","payload":{"payment":{"entity":{'
        b'"id":"' + payment_id.encode() + b'",'
        b'"amount":149900,"currency":"INR","status":"failed",'
        b'"error_code":"CARD_IS_EXPIRED","error_description":"The card has expired",'
        b'"email":"test@example.com","contact":"+919812345678"}}}}'
    )


def test_full_webhook_flow() -> None:
    init_db()
    client = TestClient(app)
    body = make_event()
    sig, event_id = sign(body)

    resp = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": event_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "accepted"

    with SessionLocal() as db:
        case = db.query(Case).filter(Case.source_ref == "pay_TEST123").one()
        assert case.amount == 149900
        assert case.failure_code == "CARD_IS_EXPIRED"

    dup = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": event_id},
    )
    assert dup.json()["status"] == "duplicate_ignored"
    with SessionLocal() as db:
        assert db.query(RawEvent).count() >= 1

    bad_sig = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": "deadbeef", "X-Razorpay-Event-Id": "evt_bad"},
    )
    assert bad_sig.status_code == 400
    print("WEBHOOK FLOW TEST PASSED: accepted -> case created -> dedup works -> bad signature rejected")


if __name__ == "__main__":
    test_full_webhook_flow()
