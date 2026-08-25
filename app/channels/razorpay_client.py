import base64

import httpx

from app.config import get_settings

BASE_URL = "https://api.razorpay.com/v1"


def _auth() -> tuple[str, str]:
    s = get_settings()
    if not s.has_live_keys:
        raise RuntimeError("Razorpay test keys not configured in .env")
    return (s.rzp_key_id, s.rzp_key_secret)


class RazorpayClient:
    def __init__(self) -> None:
        self._client = httpx.Client(base_url=BASE_URL, auth=_auth(), timeout=15.0)

    def balance(self) -> dict:
        r = self._client.get("/balance")
        r.raise_for_status()
        return r.json()

    def fetch_payment(self, payment_id: str) -> dict:
        r = self._client.get(f"/payments/{payment_id}")
        r.raise_for_status()
        return r.json()

    def fetch_subscription(self, subscription_id: str) -> dict:
        r = self._client.get(f"/subscriptions/{subscription_id}")
        r.raise_for_status()
        return r.json()

    def create_payment_link(self, amount: int, customer: dict, description: str, reference_id: str) -> dict:
        payload = {
            "amount": amount,
            "currency": "INR",
            "accept_partial": False,
            "reference_id": reference_id,
            "description": description,
            "customer": {
                "name": customer["name"],
                "contact": customer["phone"],
                "email": customer.get("email") or "",
            },
            "notify": {"sms": True, "email": True},
            "reminder_enable": False,
        }
        r = self._client.post("/payment_links", json=payload)
        r.raise_for_status()
        return r.json()

    def retry_subscription_charge(self, subscription_id: str, amount: int) -> dict:
        payload = {"amount": amount, "retry": True}
        r = self._client.post(f"/subscriptions/{subscription_id}/resume", json={})
        if r.status_code == 400:
            return {"resumed": False, "detail": r.json()}
        r.raise_for_status()
        return {"resumed": True, **r.json()}

    def close(self) -> None:
        self._client.close()


def verify_payment_link_paid(link_response: dict) -> bool:
    status = link_response.get("status", "")
    return status == "paid"
