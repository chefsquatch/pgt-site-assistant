"""Contact form: validate a lead and deliver it to the founder's inbox.

This is a separate seam from the chat assistant — it shares nothing with the
grounding rails or the chat JSON contract. Its whole job is to capture a visitor's
message and email it to Les, reliably, so nothing depends on the visitor having a
mail client configured (the flaw in the old mailto: link).

Delivery is transactional email via Resend (no datastore): an email survives a
Render redeploy, where an ephemeral-disk file would silently drop leads. The
submitter's address is set as reply-to so Les replies straight from his inbox.

Server-side validation is the guarantee, not the widget's client-side checks:
EmailStr is the idiomatic email-format gate, every field is length-capped to bound
the payload, and a hidden honeypot field catches bots.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel, EmailStr, Field, field_validator

from . import config

RESEND_ENDPOINT = "https://api.resend.com/emails"

# Field caps — bound the payload so a huge body can't be forced through.
MAX_EMAIL = 254   # RFC 5321 practical maximum
MAX_NAME = 100
MAX_MESSAGE = 5000
MAX_HONEYPOT = 200


class ContactError(Exception):
    """Base class for expected, user-facing contact failures."""


class ContactConfigError(ContactError):
    """Delivery isn't configured (missing RESEND_API_KEY)."""


class ContactDeliveryError(ContactError):
    """The email service call failed."""


class ContactRequest(BaseModel):
    # EmailStr IS the server-side email-format validation, done idiomatically.
    email: EmailStr
    message: str = Field(..., max_length=MAX_MESSAGE)
    name: str | None = Field(default=None, max_length=MAX_NAME)
    # Honeypot: a hidden field no real person sees. Bots fill it; humans leave it
    # blank. Capped so it can't be used as a payload smuggling channel either.
    company: str = Field(default="", max_length=MAX_HONEYPOT)

    @field_validator("email")
    @classmethod
    def _email_len(cls, v: str) -> str:
        if len(v) > MAX_EMAIL:
            raise ValueError("Email address is too long.")
        return v

    @field_validator("message")
    @classmethod
    def _message_non_empty(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("Message must not be empty.")
        return s

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s or None

    def is_bot(self) -> bool:
        """True when the honeypot was filled — treat as spam, silently."""
        return bool(self.company.strip())


def send_lead(req: ContactRequest) -> None:
    """Email the lead to the founder via Resend, with reply-to = the submitter."""
    if not config.RESEND_API_KEY:
        # Should never happen: startup refuses to boot without the key. Guard anyway.
        raise ContactConfigError("RESEND_API_KEY is not set; cannot deliver the message.")

    who = req.name or req.email
    subject = f"New message from the PGT site — {who}"
    text = (
        "A visitor sent this through the PGT site assistant contact form.\n\n"
        f"Name:  {req.name or '(not given)'}\n"
        f"Email: {req.email}\n\n"
        "Message:\n"
        f"{req.message}\n\n"
        "— Reply directly to this email to reach them.\n"
    )
    payload = {
        "from": config.RESEND_FROM,
        "to": [config.LEAD_INBOX],
        "reply_to": req.email,
        "subject": subject,
        "text": text,
    }
    try:
        resp = httpx.post(
            RESEND_ENDPOINT,
            json=payload,
            headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
            timeout=15,
        )
    except Exception as exc:  # network / DNS / timeout
        raise ContactDeliveryError(f"Could not reach the email service: {exc}") from exc

    if resp.status_code >= 300:
        raise ContactDeliveryError(
            f"Email service returned {resp.status_code}: {resp.text[:200]}"
        )
