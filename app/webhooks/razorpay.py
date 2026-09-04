import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import get_settings
from app.ingest import ingest_event, verify_signature

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(default=""),
    x_razorpay_event_id: str = Header(default=""),
) -> dict:
    body = await request.body()

    if not verify_signature(body, x_razorpay_signature, get_settings().rzp_webhook_secret):
        raise HTTPException(status_code=400, detail="invalid signature")

    try:
        event = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="malformed JSON body")
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="event payload must be a JSON object")

    if not x_razorpay_event_id:
        x_razorpay_event_id = event.get("id", "")

    return ingest_event(event, body, x_razorpay_signature, x_razorpay_event_id)
