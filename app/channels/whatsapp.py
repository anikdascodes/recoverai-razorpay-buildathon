"""WhatsApp channel via Twilio.

Live mode requires TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN /
TWILIO_WHATSAPP_FROM. Without credentials the channel runs in simulated
mode: the send is recorded as ``simulated`` and never claimed as delivered.
"""

import httpx

from app.config import get_settings


def send_whatsapp(phone: str, message: str) -> dict:
    s = get_settings()
    if not s.has_twilio:
        return {"mode": "simulated", "reason": "twilio_credentials_not_configured"}

    r = httpx.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}/Messages.json",
        auth=(s.twilio_account_sid, s.twilio_auth_token),
        data={
            "From": s.twilio_whatsapp_from,
            "To": f"whatsapp:{phone}",
            "Body": message,
        },
        timeout=15.0,
    )
    if r.status_code in (200, 201):
        return {"mode": "live", "sid": r.json().get("sid", "")}
    return {"mode": "live", "error": f"twilio {r.status_code}: {r.text[:120]}"}
