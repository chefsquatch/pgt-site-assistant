"""Availability store — Brick 5: the admin edits the schedule; it lives as DATA.

F2 (deterministic honesty) is the reason this module exists: the assistant must read
availability from the structured store, never from corpus prose, and never invent a
slot. So availability is three tenant-scoped tables, edited by the admin, and one
deterministic read — `open_windows()` — that Brick 6 will book against.

The shape is ported from Tinker's schedule (src/schedule/types.ts): a weekday is 0-6
with 0 = Sunday, and times are "HH:mm" local to the business. Three tables:

  * availability_settings — one row per tenant: its IANA timezone. Absent row = the
    default timezone (PGT is in Flint, MI).
  * availability_window   — recurring weekly hours: (weekday, start, end), local time.
  * availability_block    — time that is NOT available (a day off, an appointment),
    as absolute instants. `source` says who wrote it: 'manual' (the admin, this brick),
    'calendar' (a future calendar-sync brick writing the business's busy times into
    this SAME table), or 'booking' (Brick 6: a slot the assistant booked). Either way the assistant reads one store — sync is a writer, never
    a second source of truth.

Every function goes through `with_tenant()` (F1) AND carries an explicit `tenant_id`
in its SQL (F6) — writes tag it, reads/deletes filter it — because Neon's role bypasses
RLS. A delete for another tenant's id matches nothing.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import db

DEFAULT_TIMEZONE = "America/Detroit"
BLOCK_SOURCES = ("manual", "calendar", "booking")
# How far ahead open_windows() will compute in one call — bounds the work per request.
MAX_DAYS = 62

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class AvailabilityError(ValueError):
    """Bad admin input (unknown timezone, end before start, ...). Callers map it to 400."""


# --- validation -------------------------------------------------------------------

def parse_hhmm(value: str) -> time:
    m = _HHMM.match((value or "").strip())
    if not m:
        raise AvailabilityError(f"time must be HH:mm (24h), got {value!r}")
    return time(int(m.group(1)), int(m.group(2)))


def validate_timezone(name: str) -> str:
    name = (name or "").strip()
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise AvailabilityError(f"unknown timezone {name!r} (use an IANA name like America/Detroit)")
    return name


def _is_uuid(value: str) -> bool:
    """An id that is not a uuid matches no row — checked here so a malformed id is a
    clean "not found", not a database type error."""
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def _hhmm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


# --- settings -----------------------------------------------------------------------

def get_timezone(conn: db.psycopg.Connection, tenant_id: Any) -> str:
    row = db.with_tenant(
        conn,
        tenant_id,
        lambda c: c.execute(
            "SELECT timezone FROM availability_settings WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone(),
    )
    return row[0] if row else DEFAULT_TIMEZONE


def set_timezone(conn: db.psycopg.Connection, tenant_id: Any, name: str) -> str:
    name = validate_timezone(name)
    db.with_tenant(
        conn,
        tenant_id,
        lambda c: c.execute(
            "INSERT INTO availability_settings (tenant_id, timezone) VALUES (%s, %s) "
            "ON CONFLICT (tenant_id) DO UPDATE SET timezone = EXCLUDED.timezone",
            (tenant_id, name),
        ),
    )
    return name


# --- weekly windows ------------------------------------------------------------------

def add_window(
    conn: db.psycopg.Connection,
    tenant_id: Any,
    *,
    weekday: int,
    start: str,
    end: str,
    label: str | None = None,
) -> str:
    if not isinstance(weekday, int) or not 0 <= weekday <= 6:
        raise AvailabilityError("weekday must be 0-6 (0 = Sunday)")
    s, e = parse_hhmm(start), parse_hhmm(end)
    if e <= s:
        raise AvailabilityError("end must be after start (a window cannot cross midnight)")
    label = (label or "").strip() or None

    def _insert(c):
        return str(
            c.execute(
                "INSERT INTO availability_window (tenant_id, weekday, start_time, end_time, label) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (tenant_id, weekday, s, e, label),
            ).fetchone()[0]
        )

    return db.with_tenant(conn, tenant_id, _insert)


def list_windows(conn: db.psycopg.Connection, tenant_id: Any) -> list[dict]:
    rows = db.with_tenant(
        conn,
        tenant_id,
        lambda c: c.execute(
            "SELECT id, weekday, start_time, end_time, label FROM availability_window "
            "WHERE tenant_id = %s ORDER BY weekday, start_time",
            (tenant_id,),
        ).fetchall(),
    )
    return [
        {"id": str(r[0]), "weekday": r[1], "start": _hhmm(r[2]), "end": _hhmm(r[3]), "label": r[4]}
        for r in rows
    ]


def delete_window(conn: db.psycopg.Connection, tenant_id: Any, window_id: str) -> bool:
    if not _is_uuid(window_id):
        return False
    n = db.with_tenant(
        conn,
        tenant_id,
        lambda c: c.execute(
            "DELETE FROM availability_window WHERE id = %s AND tenant_id = %s",
            (window_id, tenant_id),
        ).rowcount,
    )
    return n > 0


# --- blocks --------------------------------------------------------------------------

def parse_local(value: str, tz_name: str) -> datetime:
    """Parse 'YYYY-MM-DDTHH:MM' (what <input type=datetime-local> sends) as wall time in
    the tenant's timezone. An explicit offset in the string is honored as given."""
    try:
        dt = datetime.fromisoformat((value or "").strip())
    except ValueError:
        raise AvailabilityError(f"date/time must be YYYY-MM-DDTHH:MM, got {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt


def add_block(
    conn: db.psycopg.Connection,
    tenant_id: Any,
    *,
    starts_at: datetime,
    ends_at: datetime,
    reason: str | None = None,
    source: str = "manual",
) -> str:
    if starts_at.tzinfo is None or ends_at.tzinfo is None:
        raise AvailabilityError("block times must be timezone-aware")
    if ends_at <= starts_at:
        raise AvailabilityError("block end must be after its start")
    if source not in BLOCK_SOURCES:
        raise AvailabilityError(f"source must be one of {BLOCK_SOURCES}")
    reason = (reason or "").strip() or None

    def _insert(c):
        return str(
            c.execute(
                "INSERT INTO availability_block (tenant_id, starts_at, ends_at, reason, source) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (tenant_id, starts_at, ends_at, reason, source),
            ).fetchone()[0]
        )

    return db.with_tenant(conn, tenant_id, _insert)


def list_blocks(
    conn: db.psycopg.Connection,
    tenant_id: Any,
    *,
    overlapping: tuple[datetime, datetime] | None = None,
) -> list[dict]:
    """A tenant's blocks, soonest first. `overlapping=(a, b)` limits to blocks that
    intersect [a, b) — what open_windows() needs."""
    sql = (
        "SELECT id, starts_at, ends_at, reason, source FROM availability_block "
        "WHERE tenant_id = %s"
    )
    params: list[Any] = [tenant_id]
    if overlapping is not None:
        sql += " AND starts_at < %s AND ends_at > %s"
        params += [overlapping[1], overlapping[0]]
    sql += " ORDER BY starts_at"
    rows = db.with_tenant(conn, tenant_id, lambda c: c.execute(sql, params).fetchall())
    return [
        {"id": str(r[0]), "starts_at": r[1], "ends_at": r[2], "reason": r[3], "source": r[4]}
        for r in rows
    ]


def delete_block(conn: db.psycopg.Connection, tenant_id: Any, block_id: str) -> bool:
    if not _is_uuid(block_id):
        return False
    n = db.with_tenant(
        conn,
        tenant_id,
        lambda c: c.execute(
            "DELETE FROM availability_block WHERE id = %s AND tenant_id = %s",
            (block_id, tenant_id),
        ).rowcount,
    )
    return n > 0


# --- the deterministic read ------------------------------------------------------------

@dataclass(frozen=True)
class OpenWindow:
    start: datetime  # timezone-aware, in the tenant's zone
    end: datetime


def compute_open_windows(
    windows: Iterable[dict],
    blocks: Iterable[tuple[datetime, datetime]],
    tz_name: str,
    start_date: date,
    days: int,
) -> list[OpenWindow]:
    """Pure: the open time over [start_date, start_date + days) — each local day's
    weekly windows, minus every block — as aware datetimes in the tenant's zone.

    Wall-clock times are resolved per DATE through zoneinfo, so a 9:00 window is 9:00
    local on both sides of a DST change. Blocks are absolute instants; a block that
    covers part of a window splits it. Same inputs, same output — no clock read.
    """
    tz = ZoneInfo(tz_name)
    by_day: dict[int, list[tuple[time, time]]] = {}
    for w in windows:
        by_day.setdefault(w["weekday"], []).append((parse_hhmm(w["start"]), parse_hhmm(w["end"])))
    cuts = sorted((a.astimezone(timezone.utc), b.astimezone(timezone.utc)) for a, b in blocks)

    out: list[OpenWindow] = []
    for i in range(days):
        d = start_date + timedelta(days=i)
        weekday = (d.weekday() + 1) % 7  # Python Mon=0 -> Tinker/engine Sun=0
        for s, e in sorted(by_day.get(weekday, [])):
            pieces = [(datetime.combine(d, s, tz), datetime.combine(d, e, tz))]
            for b_start, b_end in cuts:
                nxt = []
                for p_start, p_end in pieces:
                    if b_end <= p_start or b_start >= p_end:
                        nxt.append((p_start, p_end))
                        continue
                    if b_start > p_start:
                        nxt.append((p_start, b_start.astimezone(tz)))
                    if b_end < p_end:
                        nxt.append((b_end.astimezone(tz), p_end))
                pieces = nxt
            out.extend(OpenWindow(a, b) for a, b in pieces if b > a)
    out.sort(key=lambda w: w.start)
    return out


def open_windows(
    conn: db.psycopg.Connection,
    tenant_id: Any,
    *,
    start_date: date | None = None,
    days: int = 14,
) -> list[OpenWindow]:
    """The tenant's open time, read from the store (F2). `start_date` defaults to today
    in the tenant's zone. This is the read Brick 6 books against."""
    if not 1 <= days <= MAX_DAYS:
        raise AvailabilityError(f"days must be 1-{MAX_DAYS}")
    tz_name = get_timezone(conn, tenant_id)
    tz = ZoneInfo(tz_name)
    if start_date is None:
        start_date = datetime.now(tz).date()
    span = (
        datetime.combine(start_date, time(0), tz),
        datetime.combine(start_date + timedelta(days=days), time(0), tz),
    )
    blocks = [(b["starts_at"], b["ends_at"]) for b in list_blocks(conn, tenant_id, overlapping=span)]
    return compute_open_windows(list_windows(conn, tenant_id), blocks, tz_name, start_date, days)


# --- Brick 6: slots + booking ---------------------------------------------------------
# Founder rulings 2026-10-26: slots are 30 minutes, the horizon is 2 weeks, and a booking
# blocks its slot INSTANTLY (no approval step) by writing an availability_block with
# source='booking'. So a booking is just another block in the one store: it disappears
# from open_windows() the moment it is written, and the admin cancels one by deleting
# its block.

SLOT_MINUTES = 30
BOOKING_DAYS = 14
_SLOT = timedelta(minutes=SLOT_MINUTES)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class SlotUnavailable(AvailabilityError):
    """The slot asked for is not open (taken, past, never existed). Never booked."""


@dataclass(frozen=True)
class Slot:
    start: datetime  # timezone-aware, in the tenant's zone
    end: datetime

    @property
    def id(self) -> str:
        """The handle the assistant copies back: local wall time 'YYYY-MM-DDTHH:MM'."""
        return self.start.strftime("%Y-%m-%dT%H:%M")

    @property
    def label(self) -> str:
        """What a person reads: 'Tue Oct 27, 10:00 AM EDT'. Built by hand because the
        no-padding strftime flags differ between platforms."""
        s = self.start
        hour = s.hour % 12 or 12
        return f"{s:%a %b} {s.day}, {hour}:{s:%M} {'AM' if s.hour < 12 else 'PM'} {s:%Z}"


def compute_slots(open_windows_: Iterable[OpenWindow], now: datetime) -> list[Slot]:
    """Pure: every 30-minute slot that fits wholly inside an open window and starts after
    `now`.

    ⚠ LOAD-BEARING: slots sit on a FIXED grid (:00 and :30), aligned to absolute time, not
    to each window's start. That makes "two bookings overlap" the same thing as "two
    bookings share a start", which is what the unique index on booking starts enforces
    (availability_booking_slot_uq) so two people can never book one slot. A window that
    starts off the grid (9:15) loses its partial first cell. Absolute alignment equals the
    local :00/:30 grid for every zone whose offset is a whole half hour (all US zones), and
    it stays right across DST because it never reads a wall clock.
    """
    out: list[Slot] = []
    for w in open_windows_:
        tz = w.start.tzinfo
        elapsed = w.start.astimezone(timezone.utc) - _EPOCH
        t = w.start.astimezone(timezone.utc) + (-elapsed % _SLOT)  # round up onto the grid
        while t + _SLOT <= w.end:
            if t > now:
                out.append(Slot(t.astimezone(tz), (t + _SLOT).astimezone(tz)))
            t += _SLOT
    return out


def open_slots(
    conn: db.psycopg.Connection,
    tenant_id: Any,
    *,
    now: datetime | None = None,
) -> list[Slot]:
    """The tenant's bookable slots over the next two weeks, read from the store (F2).
    Empty when the tenant has no weekly hours, which keeps booking off for that tenant."""
    tz = ZoneInfo(get_timezone(conn, tenant_id))
    now = now or datetime.now(timezone.utc)
    wins = open_windows(conn, tenant_id, start_date=now.astimezone(tz).date(), days=BOOKING_DAYS)
    return compute_slots(wins, now)


def book_slot(
    conn: db.psycopg.Connection,
    tenant_id: Any,
    slot_id: str,
    *,
    reason: str | None,
    now: datetime | None = None,
) -> Slot:
    """Book one slot, instantly, by writing a source='booking' block. Raises
    SlotUnavailable unless `slot_id` is one of the tenant's open slots RIGHT NOW: the
    assistant only ever proposes an id, and the store decides. A concurrent booking of the
    same slot loses at the unique index and is reported the same way.

    `conn` must be autocommit (the request-path contract), so the block commits on return.
    """
    slot = next((s for s in open_slots(conn, tenant_id, now=now) if s.id == slot_id), None)
    if slot is None:
        raise SlotUnavailable(f"slot {slot_id!r} is not open")
    try:
        add_block(conn, tenant_id, starts_at=slot.start, ends_at=slot.end, reason=reason, source="booking")
    except db.psycopg.errors.UniqueViolation:
        raise SlotUnavailable(f"slot {slot_id!r} was just booked")
    return slot


def slots_for_prompt(slots: list[Slot], limit: int = 120) -> str:
    """The open slots as compact text for the assistant, one line per day:
    'Tue Oct 27: 2026-10-27T09:00, 2026-10-27T09:30'. Capped so a wide-open calendar
    can't flood the prompt; the cap keeps the SOONEST slots."""
    days: dict[str, list[str]] = {}
    for s in slots[:limit]:
        days.setdefault(f"{s.start:%a %b} {s.start.day} ({s.start:%Z})", []).append(s.id)
    return "\n".join(f"{day}: {', '.join(ids)}" for day, ids in days.items())
