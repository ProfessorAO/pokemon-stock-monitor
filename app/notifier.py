from __future__ import annotations

import logging

import httpx

from .config import Settings

logger = logging.getLogger("stock_monitor.notifier")


def send_sms(settings: Settings, body: str) -> bool:
    """Send an SMS via Twilio. Returns True on success.

    A leading newline is prepended so Twilio's trial-account tag
    ("Sent from your Twilio trial account - ") lands on its own line
    instead of running into the alert text.
    """
    if not settings.sms_enabled:
        logger.info("SMS disabled (missing Twilio config); alert not sent: %s", body)
        return False

    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
    try:
        response = httpx.post(
            url,
            data={
                "To": settings.twilio_to_number,
                "From": settings.twilio_from_number,
                "Body": "\n" + body,
            },
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            timeout=20,
        )
    except httpx.HTTPError as exc:
        logger.error("Failed to reach Twilio: %s", exc)
        return False

    if response.status_code >= 300:
        logger.error("Twilio SMS send failed (%s): %s", response.status_code, response.text)
        return False

    logger.info("SMS sent: %s", body.splitlines()[0] if body else "")
    return True
