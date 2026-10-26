"""Booking seam — Brick 6: the assistant books against the store, deterministically.

The request paths call two things here, and both are best-effort like the lead seam
(app/leads.py): a store that is unset or briefly down must never break the reply the
visitor is waiting on. Without a store there are simply no slots, and the assistant
behaves exactly as it did before this brick.

  * read_slots()  — the tenant's open slots (availability.open_slots, F2). Empty when the
    tenant has no weekly hours, which is what keeps booking off for that tenant.
  * try_book()    — the model PROPOSED a slot; the store decides. On success the slot is
    blocked instantly (founder ruling 2026-10-26), the booking is recorded as a lead, and
    the owner is emailed. Either way the visitor's reply is written HERE, from what the
    store actually did, never from what the model said.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from . import availability, config, db, notify
from .leads import create_lead

log = logging.getLogger(__name__)


@dataclass
class BookingOutcome:
    reply: str  # what the visitor reads, written from the store's answer
    slot: availability.Slot | None = None  # set only when the booking was written
    lead: dict | None = None  # the lead recorded for it


def _open() -> db.psycopg.Connection:
    # Autocommit: each with_tenant is its own committed txn (the lead seam's contract).
    conn = db.connect()
    conn.autocommit = True
    return conn


def read_slots(conn: db.psycopg.Connection, tenant_id: Any) -> list[availability.Slot]:
    """Open slots for the tenant, or [] if the store read fails. Never raises."""
    try:
        return availability.open_slots(conn, tenant_id)
    except Exception:
        log.exception("slot read failed tenant=%s; booking off for this turn", tenant_id)
        return []


def _list_times(slots: list[availability.Slot]) -> str:
    labels = [s.label for s in slots]
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " or " + labels[-1]


def try_book(
    tenant: dict,
    book: dict,
    *,
    summary: str | None,
    transcript: list[dict],
    pgt: bool,
) -> BookingOutcome:
    """Book `book['slot']` for the tenant if, and only if, the store says it is open.
    `pgt` picks the flavor's wording: PGT books a call-back from Les; a client tenant
    books a plain appointment. Never raises."""
    business = tenant.get("name") or "the business"
    who = ", ".join(v for v in (book["name"], book["phone"], book.get("email")) if v)
    try:
        conn = _open()
    except Exception:
        log.warning("booking not made: store unavailable tenant=%s", tenant.get("slug"))
        return BookingOutcome(
            reply="Sorry, I can't reach the calendar right now, so nothing is booked yet. "
            "Please try again in a minute."
        )
    try:
        try:
            slot = availability.book_slot(
                conn, tenant["id"], book["slot"], reason=f"Booked by the assistant: {who}"
            )
        except availability.SlotUnavailable:
            nxt = read_slots(conn, tenant["id"])[:3]
            if nxt:
                return BookingOutcome(
                    reply=f"Sorry, that time isn't open. The next open times are {_list_times(nxt)}. "
                    "Which works for you?"
                )
            return BookingOutcome(
                reply="Sorry, that time isn't open and there are no other open times right now. "
                f"{'Les will reply by email' if pgt else business + ' will follow up'} to find a time."
            )

        what = f"{'Call-back' if pgt else 'Appointment'} booked for {slot.label}"
        lead = {
            "name": book["name"],
            "phone": book["phone"],
            "email": book.get("email"),
            "summary": f"{what}. {summary or ''}".strip(),
            "urgent": False,
            "booking": slot.label,
        }
        try:
            create_lead(
                conn,
                tenant["id"],
                problem_summary=lead["summary"],
                name=lead["name"],
                email=lead["email"],
                phone=lead["phone"],
                source="assistant",
            )
        except Exception:
            # The slot IS booked (its block is committed); the admin sees it in the block
            # list even if the lead row failed, and the email below still goes out.
            log.exception("booking lead not stored tenant=%s", tenant.get("slug"))
    except Exception:
        log.exception("booking failed tenant=%s", tenant.get("slug"))
        return BookingOutcome(
            reply="Sorry, something went wrong and nothing is booked yet. Please try again in a minute."
        )
    finally:
        conn.close()

    notify.email_lead(tenant, lead, transcript)
    if pgt:
        reply = (
            f"Done, you're booked: Les will call you at {book['phone']} on {slot.label}. "
            f"If anything changes, email him at {config.FOUNDER_EMAIL}."
        )
    else:
        reply = f"Done, you're booked for {slot.label}. {business} has your details."
    return BookingOutcome(reply=reply, slot=slot, lead=lead)


def slot_json(slot: availability.Slot | None) -> dict | None:
    if slot is None:
        return None
    return {"slot": slot.id, "label": slot.label, "start": slot.start.isoformat()}
