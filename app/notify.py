"""Client lead alerts (Brick 4b, 2026-10-25): email a captured lead to the tenant's owner.

Ported from the vertical-demos lead email (founder 2026-10-24: "fork at emailing me"), on the
same Resend rail as app/contact.py. The store is the system of record; this email is the
owner's notification, so it is BEST-EFFORT: it never raises, and a failed send is logged and
reported as False. A copy goes to PGT (LEAD_INBOX) so the founder sees every client lead while
the first clients are onboarding.
"""

from __future__ import annotations

import logging

import httpx

from . import config
from .contact import RESEND_ENDPOINT

log = logging.getLogger(__name__)


def lead_email_text(business: str, lead: dict, transcript: list[dict]) -> str:
    lines = [
        f"New lead from your website assistant ({business}).",
        "",
        f"Name:    {lead.get('name') or ''}",
        f"Phone:   {lead.get('phone') or ''}",
        f"Email:   {lead.get('email') or ''}",
        f"Wants:   {lead.get('summary') or ''}",
        f"Urgent:  {'YES' if lead.get('urgent') else 'no'}",
        "",
        "Conversation:",
    ]
    for m in transcript:
        who = "Customer" if m.get("role") == "user" else "Assistant"
        lines.append(f"{who}: {str(m.get('content', '')).strip()}")
    lines += ["", "Every lead is also saved to your leads page."]
    return "\n".join(lines)


def email_lead(tenant: dict, lead: dict, transcript: list[dict]) -> bool:
    """Send the lead to the tenant's notify_email (copy to PGT). Never raises."""
    if not config.CLIENT_RESEND_API_KEY:
        log.warning("lead alert not sent: no Resend key set tenant=%s", tenant.get("slug"))
        return False
    to = [a for a in [tenant.get("notify_email")] if a]
    cc = [config.LEAD_INBOX] if config.LEAD_INBOX and config.LEAD_INBOX not in to else []
    if not to:
        to, cc = cc, []
    if not to:
        return False
    urgent = "URGENT " if lead.get("urgent") else ""
    payload = {
        "from": config.CLIENT_LEAD_FROM,
        "to": to,
        "subject": f"{urgent}New lead: {lead.get('name') or 'a customer'} ({tenant.get('name')})",
        "text": lead_email_text(tenant.get("name") or "", lead, transcript),
    }
    if cc:
        payload["cc"] = cc
    if lead.get("email"):
        payload["reply_to"] = lead["email"]
    try:
        resp = httpx.post(
            RESEND_ENDPOINT,
            json=payload,
            headers={"Authorization": f"Bearer {config.CLIENT_RESEND_API_KEY}"},
            timeout=10,
        )
    except Exception as exc:
        log.error("lead alert failed tenant=%s: %s", tenant.get("slug"), exc)
        return False
    if resp.status_code >= 300:
        log.error("lead alert failed tenant=%s status=%s %s", tenant.get("slug"), resp.status_code, resp.text[:200])
        return False
    log.info("lead alert sent tenant=%s to=%s", tenant.get("slug"), to)
    return True
