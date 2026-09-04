"""World simulator.

In production the only way money is confirmed is a signed Razorpay webhook
(``subscription.charged``, ``payment_link.paid``). In test mode with synthetic
customers, nothing can actually charge — so this module plays the role of the
outside world: after the agent executes an action, it decides whether the
customer would have paid, and if so, emits the exact event Razorpay would
have emitted, HMAC-signed, through the same ingest path as live traffic.

The agent never learns the outcome directly. Recovery is only ever confirmed
by an event flowing through ingress — identical mechanics to production.
"""

import hashlib
import hmac
import json
import random
import uuid

from app.config import get_settings
from app.ingest import ingest_event
from app.models import Case

SUCCESS_PROBABILITY = {
    "auto_retry": 0.85,
    "whatsapp_reminder": 0.55,
    "payment_link_update_card": 0.65,
    "voice_call": 0.70,
    "mandate_relink": 0.30,
    "pause_and_offer": 0.35,
}


def reference_id_for(case_id: int, round_no: int) -> str:
    return f"recoverai_case_{case_id}_r{round_no}"


def _signed_ingest(event: dict) -> dict:
    secret = get_settings().rzp_webhook_secret
    body = json.dumps(event, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return ingest_event(event, body, signature, f"evt_sim_{uuid.uuid4().hex[:16]}")


def settle_action(case: Case, action: str, round_no: int) -> dict:
    """Simulate the customer/world response to an executed action.

    Returns {"paid": bool, "event_type": str | None, "ingest": dict | None}.
    """
    paid = random.random() < SUCCESS_PROBABILITY.get(action, 0.4)
    if not paid:
        return {"paid": False, "event_type": None, "ingest": None}

    if action == "auto_retry":
        # A successful retry charge surfaces as subscription.charged.
        event = {
            "event": "subscription.charged",
            "payload": {
                "subscription": {
                    "entity": {"id": case.subscription_id, "status": "active"}
                }
            },
        }
    else:
        # Payment-link flows surface as payment_link.paid, matched by the
        # reference_id the agent embedded when creating the link.
        event = {
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {
                    "entity": {
                        "id": f"plink_SIM{random.randint(10**8, 10**9 - 1)}",
                        "status": "paid",
                        "reference_id": reference_id_for(case.id, round_no),
                        "amount": case.amount,
                    }
                }
            },
        }
    result = _signed_ingest(event)
    return {"paid": True, "event_type": event["event"], "ingest": result}


def late_authorization(case_ref: str) -> dict:
    """Emit a payment.captured event for a payment that failed earlier but
    was authorized by the issuing bank afterwards (the late-authorization
    reconciliation scenario)."""
    event = {
        "event": "payment.captured",
        "payload": {
            "payment": {"entity": {"id": case_ref, "status": "captured"}}
        },
    }
    return _signed_ingest(event)
