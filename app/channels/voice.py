"""Hinglish voice recovery channel.

Bounded by design: the call script is drafted by the planner from a fixed
template family, capped at 6 sentences, always opens with an identity +
consent line and always offers a digital self-serve option (the payment
link) so the customer never has to transact over the call.

Live mode (Sarvam TTS for code-mixed Hinglish + Twilio Voice) requires
SARVAM_API_KEY and Twilio credentials. Without them, the channel records
the bounded script as ``script_only`` — the script is real, reviewable and
replayable on the dashboard; no call is placed or claimed.
"""

from app.config import get_settings

MAX_SCRIPT_SENTENCES = 6
CONSENT_OPENING = (
    "Namaste, main {name} ke liye RecoverAI se bol raha hoon. "
    "Aapki {amount_rs} rupees ki subscription payment fail hui thi. "
    "Kya main 30 second mein help kar sakta hoon?"
)


def build_script(name: str, amount_rs: float, lang_pref: str, payment_link: str) -> str:
    if lang_pref == "en":
        opening = (
            f"Hello, this is RecoverAI calling on behalf of {name}. "
            f"Your subscription payment of Rs {amount_rs:.0f} did not go through. "
            "May I help you fix it in 30 seconds?"
        )
        closing = (
            f"I have sent a payment link: {payment_link}. "
            "Tap it to pay securely right now. Thank you!"
        )
    else:
        opening = CONSENT_OPENING.format(name=name, amount_rs=f"{amount_rs:.0f}")
        closing = (
            f"Aapke liye payment link bheja hai: {payment_link}. "
            "Us par tap karke aap turant pay kar sakte hain. Dhanyavaad!"
        )
    return f"{opening} {closing}"


def _count_sentences(script: str) -> int:
    import re

    without_urls = re.sub(r"https?://\S+", "URL", script)
    return len([x for x in re.split(r"[.!?]+", without_urls) if x.strip()])


def place_call(phone: str, script: str) -> dict:
    s = get_settings()
    if _count_sentences(script) > MAX_SCRIPT_SENTENCES:
        return {"mode": "blocked", "reason": "script_exceeds_bounded_length"}

    if not (s.has_twilio and s.sarvam_api_key):
        return {"mode": "script_only", "reason": "voice_credentials_not_configured", "script": script}

    # Live path: Sarvam TTS -> Twilio Voice with the audio as <Play>.
    # Requires a provisioned voice number; kept behind credentials so the
    # simulated path above is what runs in the demo environment.
    return {"mode": "live", "error": "voice live path not provisioned for this environment"}
