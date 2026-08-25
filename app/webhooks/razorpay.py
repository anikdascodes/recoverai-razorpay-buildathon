import hmac
import hashlib
import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import RawEvent, utcnow
from app.normalizer import normalize_event

logger = logging.getLogger(__name__)
router = APIRouter()

RECOVERY_EVENTS = {
    "payment.failed",
    "subscription.pending",
    "subscription.charged",
    "subscription.halted",
    "invoice.paid",
}


def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_razorpay_signature: str = Header(default=""),
    x_razorpay_event_id: str = Header(default=""),
) -> dict:
    body = await request.body()
    settings = get_settings()

    if not verify_signature(body, x_razorpay_signature, settings.rzp_webhook_secret):
        raise HTTPException(status_code=400, detail="invalid signature")

    event = await request.json()
    event_type = event.get("event", "")
    if not x_razorpay_event_id:
        x_razorpay_event_id = event.get("id", f"synthetic-{utcnow().timestamp()}")

    with SessionLocal() as db:
        existing = db.scalar(select(RawEvent).where(RawEvent.event_id == x_razorpay_event_id))
        if existing is not None:
            return {"status": "duplicate_ignored", "event_id": x_razorpay_event_id}

        raw = RawEvent(event_id=x_razorpay_event_id, event_type=event_type, payload=event)
        db.add(raw)
        db.commit()

    if event_type in RECOVERY_EVENTS:
        background_tasks.add_task(safe_normalize, x_razorpay_event_id)

    return {"status": "accepted", "event_id": x_razorpay_event_id}


def safe_normalize(event_id: str) -> None:
    try:
        with SessionLocal() as db:
            raw = db.scalar(select(RawEvent).where(RawEvent.event_id == event_id))
            if raw is None or raw.processed:
                return
            case_id = normalize_event(db, raw)
            raw.processed = True
            db.commit()
            logger.info("event %s -> case %s", event_id, case_id)
    except Exception:
        logger.exception("failed to process event %s", event_id)
