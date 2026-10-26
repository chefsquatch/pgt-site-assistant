"""BRICK 6 — the assistant reads availability deterministically and books (F2).

Founder rulings 2026-10-26: a booking blocks its slot INSTANTLY (a source='booking'
availability_block, no approval step); slots are 30 minutes; the horizon is 2 weeks.

Three layers, each proven separately:
  * the slots (compute_slots) — pure, no DB: the fixed :00/:30 grid, blocks cut slots,
    past slots are gone, DST keeps wall-clock times, labels read right;
  * the store (book_slot) — a booking writes its block and the slot disappears; an
    invented, past or taken slot is refused and writes nothing; two bookings of one slot
    lose at the unique index; the wall (F1) + defense in depth (F6) hold with RLS off;
  * the routes (served behavior) — the model only ever PROPOSES a slot id; the store
    decides, and the reply the visitor reads is written from what the store did. No weekly
    hours = no slots in the prompt = booking off, exactly the pre-brick assistant.

The route tests reuse the client-tenant harness, whose app connects as the superuser
(RLS bypassed, the Neon condition), so their isolation assertions hold on F6 alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import psycopg
import pytest

from app import assistant, availability as av, config
from app.leads import list_leads
from test_client_tenants import _stub_model, env  # noqa: F401 (fixture)

TZ = ZoneInfo("America/Detroit")


def _win(y, m, d, sh, sm, eh, em):
    return av.OpenWindow(datetime(y, m, d, sh, sm, tzinfo=TZ), datetime(y, m, d, eh, em, tzinfo=TZ))


EARLY = datetime(2026, 10, 1, tzinfo=timezone.utc)  # a "now" before every window below


# --- the slots (pure) -------------------------------------------------------------------

def test_slots_sit_on_the_fixed_half_hour_grid():
    # 09:15-11:00 loses its partial first cell; every slot starts on :00 or :30.
    slots = av.compute_slots([_win(2026, 10, 27, 9, 15, 11, 0)], EARLY)
    assert [s.id for s in slots] == ["2026-10-27T09:30", "2026-10-27T10:00", "2026-10-27T10:30"]
    assert all(s.end - s.start == av._SLOT for s in slots)


def test_open_pieces_split_by_a_block_give_only_whole_slots():
    # open_windows already cut a 10:00-10:30 booking out of 09:00-12:00.
    wins = [_win(2026, 10, 27, 9, 0, 10, 0), _win(2026, 10, 27, 10, 30, 12, 0)]
    assert [s.start.strftime("%H:%M") for s in av.compute_slots(wins, EARLY)] == [
        "09:00", "09:30", "10:30", "11:00", "11:30"]


def test_past_slots_are_never_offered():
    now = datetime(2026, 10, 27, 10, 5, tzinfo=TZ)
    slots = av.compute_slots([_win(2026, 10, 27, 9, 0, 12, 0)], now)
    assert [s.start.strftime("%H:%M") for s in slots] == ["10:30", "11:00", "11:30"]


def test_dst_keeps_wall_clock_slots_and_labels():
    before = av.compute_slots([_win(2026, 10, 26, 9, 0, 10, 0)], EARLY)
    after = av.compute_slots([_win(2026, 11, 2, 9, 0, 10, 0)], EARLY)  # after the Nov 1 change
    assert [s.id for s in before] == ["2026-10-26T09:00", "2026-10-26T09:30"]
    assert [s.id for s in after] == ["2026-11-02T09:00", "2026-11-02T09:30"]
    assert before[0].label == "Mon Oct 26, 9:00 AM EDT"
    assert after[0].label == "Mon Nov 2, 9:00 AM EST"


def test_labels_read_like_a_person_wrote_them():
    slots = av.compute_slots([_win(2026, 10, 27, 12, 0, 14, 0)], EARLY)
    assert [s.label for s in slots][:3] == [
        "Tue Oct 27, 12:00 PM EDT", "Tue Oct 27, 12:30 PM EDT", "Tue Oct 27, 1:00 PM EDT"]


def test_prompt_text_groups_ids_by_day():
    slots = av.compute_slots(
        [_win(2026, 10, 27, 9, 0, 10, 0), _win(2026, 10, 28, 13, 0, 13, 30)], EARLY)
    assert av.slots_for_prompt(slots) == (
        "Tue Oct 27 (EDT): 2026-10-27T09:00, 2026-10-27T09:30\n"
        "Wed Oct 28 (EDT): 2026-10-28T13:00")
    assert av.slots_for_prompt([]) == ""


# --- the store ----------------------------------------------------------------------------

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=TZ)  # Monday noon; Tue Oct 27 is weekday 2


def _hours(tenants, tenant_id):
    av.add_window(tenants.conn, tenant_id, weekday=2, start="09:00", end="11:00")


def _ids(tenants, tenant_id):
    return [s.id for s in av.open_slots(tenants.conn, tenant_id, now=NOW) if s.id.startswith("2026-10-27")]


def _bookings(conn, tenant_id):
    return conn.execute(
        "SELECT count(*) FROM availability_block WHERE tenant_id = %s AND source = 'booking'",
        (tenant_id,),
    ).fetchone()[0]


def test_no_weekly_hours_means_no_slots(tenants):
    assert av.open_slots(tenants.conn, tenants.A, now=NOW) == []


def test_a_booking_blocks_its_slot_instantly(tenants):
    _hours(tenants, tenants.A)
    slot = av.book_slot(tenants.conn, tenants.A, "2026-10-27T09:30", reason="Dana", now=NOW)
    assert slot.label == "Tue Oct 27, 9:30 AM EDT"
    assert _ids(tenants, tenants.A) == ["2026-10-27T09:00", "2026-10-27T10:00", "2026-10-27T10:30"]
    blocks = av.list_blocks(tenants.conn, tenants.A)
    assert [(b["source"], b["reason"]) for b in blocks] == [("booking", "Dana")]
    # Booking it again is refused, and writes nothing.
    with pytest.raises(av.SlotUnavailable):
        av.book_slot(tenants.conn, tenants.A, "2026-10-27T09:30", reason="Eve", now=NOW)
    assert len(av.list_blocks(tenants.conn, tenants.A)) == 1


@pytest.mark.parametrize("slot_id", [
    "2026-10-27T09:15",  # off the grid
    "2026-10-27T12:00",  # outside the hours
    "2026-10-28T09:00",  # a day with no hours
    "2026-10-20T09:00",  # the past
    "2026-11-17T09:00",  # past the 2-week horizon (a Tuesday)
    "tomorrow at nine",  # not an id at all
])
def test_an_invented_slot_is_refused_and_writes_nothing(tenants, slot_id):
    _hours(tenants, tenants.A)
    with pytest.raises(av.SlotUnavailable):
        av.book_slot(tenants.conn, tenants.A, slot_id, reason="x", now=NOW)
    assert av.list_blocks(tenants.conn, tenants.A) == []


def test_two_bookings_of_one_slot_lose_at_the_unique_index(tenants, monkeypatch):
    _hours(tenants, tenants.A)
    av.book_slot(tenants.conn, tenants.A, "2026-10-27T10:00", reason="first", now=NOW)
    # The concurrent loser read its slots BEFORE the first booking committed: replay that
    # stale read, so only the unique index stands between it and a double booking.
    stale = av.compute_slots([_win(2026, 10, 27, 9, 0, 11, 0)], NOW)
    monkeypatch.setattr(av, "open_slots", lambda *a, **k: stale)
    with pytest.raises(av.SlotUnavailable, match="just booked"):
        av.book_slot(tenants.conn, tenants.A, "2026-10-27T10:00", reason="second", now=NOW)
    assert [b["reason"] for b in av.list_blocks(tenants.conn, tenants.A)] == ["first"]


def test_unique_index_is_per_tenant_and_per_booking(tenants):
    t = datetime(2026, 10, 27, 10, 0, tzinfo=TZ)
    end = datetime(2026, 10, 27, 10, 30, tzinfo=TZ)
    av.add_block(tenants.conn, tenants.A, starts_at=t, ends_at=end, source="booking")
    # Another tenant's booking at the same instant, and a manual block at it, are fine.
    av.add_block(tenants.conn, tenants.B, starts_at=t, ends_at=end, source="booking")
    av.add_block(tenants.conn, tenants.A, starts_at=t, ends_at=end, source="manual")
    with pytest.raises(psycopg.errors.UniqueViolation):
        av.add_block(tenants.conn, tenants.A, starts_at=t, ends_at=end, source="booking")


def test_bookings_stay_inside_the_wall_even_with_rls_off(tenants):
    _hours(tenants, tenants.A)
    _hours(tenants, tenants.B)
    av.book_slot(tenants.conn, tenants.B, "2026-10-27T09:00", reason="B's customer", now=NOW)

    def check():
        # B's booking takes B's slot, never A's: A still offers 09:00.
        assert _ids(tenants, tenants.A)[0] == "2026-10-27T09:00"
        assert _ids(tenants, tenants.B)[0] == "2026-10-27T09:30"
        assert _bookings(tenants.conn, tenants.A) == 0

    check()
    # Red control: pull the wall down (the Neon BYPASSRLS condition). The raw read leaks...
    tenants.as_owner('ALTER TABLE "availability_block" DISABLE ROW LEVEL SECURITY;')
    assert tenants.conn.execute("SELECT count(*) FROM availability_block").fetchone()[0] == 1
    # ...and the slot reads STILL isolate, because they filter tenant_id in SQL (F6).
    check()
    tenants.as_owner('ALTER TABLE "availability_block" ENABLE ROW LEVEL SECURITY;')
    tenants.as_owner('ALTER TABLE "availability_block" FORCE ROW LEVEL SECURITY;')


# --- the routes (served behavior) -----------------------------------------------------------

def _all_hours(conn, tenant_id):
    """Open every day, all day, so the route tests always have future slots."""
    for d in range(7):
        av.add_window(conn, tenant_id, weekday=d, start="00:00", end="23:59")


def _pick(conn, tenant_id) -> av.Slot:
    return av.open_slots(conn, tenant_id)[3]  # a few cells ahead, so it stays future


DANA = {"name": "Dana Cole", "phone": "810-555-0142", "email": None}


def _ask(c, slug, **extra):
    return c.post(f"/t/{slug}/chat", json={
        "history": [{"role": "user", "content": "Can I book a time?"}], **extra})


def test_no_hours_means_booking_stays_off(env, monkeypatch):
    seen = []
    _stub_model(monkeypatch, {"reply": "Leave your number.", "in_corpus": True, "lead": None,
                              "book": {**DANA, "slot": "2026-10-27T10:00"}}, seen)
    r = _ask(env["client"], "alpha")
    assert r.status_code == 200 and r.json()["booking"] is None
    assert r.json()["reply"] == "Leave your number."
    assert "OPEN TIMES" not in seen[0] and "don't hold a live calendar" in seen[0]
    assert av.list_blocks(env["conn"], env["ids"]["alpha"]) == []


def test_client_books_a_real_slot_and_the_store_writes_the_reply(env, monkeypatch):
    conn, ids = env["conn"], env["ids"]
    _all_hours(conn, ids["alpha"])
    slot = _pick(conn, ids["alpha"])
    seen = []
    _stub_model(monkeypatch, {"reply": "You're all set, see you then!", "in_corpus": True,
                              "lead": {**DANA, "summary": "Leaky water heater", "urgent": False},
                              "book": {**DANA, "slot": slot.id}}, seen)
    r = _ask(env["client"], "alpha")
    # Route: the prompt carried the real slot ids; the reply is the server's, not the model's.
    assert "OPEN TIMES" in seen[0] and slot.id in seen[0]
    body = r.json()
    assert r.status_code == 200
    assert body["booking"]["slot"] == slot.id and body["booking"]["label"] == slot.label
    assert body["reply"] == f"Done, you're booked for {slot.label}. Alpha Plumbing has your details."
    assert body["lead"] is None  # the booking is recorded as its own lead, not twice
    # Outcome: one booking block under alpha only; the slot is gone; one lead; one email.
    blocks = av.list_blocks(conn, ids["alpha"])
    assert [(b["source"], b["starts_at"]) for b in blocks] == [("booking", slot.start)]
    assert av.list_blocks(conn, ids["bravo"]) == [] and av.list_blocks(conn, ids["pgt"]) == []
    assert slot.id not in [s.id for s in av.open_slots(conn, ids["alpha"])]
    leads = list_leads(conn, ids["alpha"])
    assert [(l["name"], l["phone"]) for l in leads] == [("Dana Cole", "810-555-0142")]
    assert leads[0]["problem_summary"] == f"Appointment booked for {slot.label}. Leaky water heater"
    assert len(env["sent"]) == 1
    mail = env["sent"][0]
    assert mail["to"] == ["owner@alpha.test"] and mail["subject"].startswith(f"Booked {slot.label}")
    assert f"BOOKED:  {slot.label}" in mail["text"]


def test_an_invented_slot_from_the_model_books_nothing(env, monkeypatch):
    conn, ids = env["conn"], env["ids"]
    _all_hours(conn, ids["alpha"])
    _stub_model(monkeypatch, {"reply": "Booked you for 3:17!", "in_corpus": True, "lead": None,
                              "book": {**DANA, "slot": "2026-10-27T03:17"}})
    r = _ask(env["client"], "alpha")
    body = r.json()
    assert body["booking"] is None
    assert body["reply"].startswith("Sorry, that time isn't open. The next open times are ")
    assert "3:17" not in body["reply"]
    assert av.list_blocks(conn, ids["alpha"]) == [] and env["sent"] == []


def test_one_conversation_books_once(env, monkeypatch):
    conn, ids = env["conn"], env["ids"]
    _all_hours(conn, ids["alpha"])
    slot = _pick(conn, ids["alpha"])
    seen = []
    _stub_model(monkeypatch, {"reply": "Sure.", "in_corpus": True, "lead": None,
                              "book": {**DANA, "slot": slot.id}}, seen)
    r = _ask(env["client"], "alpha", booked=True)
    assert r.json()["booking"] is None and r.json()["reply"] == "Sure."
    assert "OPEN TIMES" not in seen[0]
    assert av.list_blocks(conn, ids["alpha"]) == []


def _pgt_ask(c, **extra):
    return c.post("/chat", json={
        "history": [{"role": "user", "content": "Could Les call me Tuesday?"}], **extra})


def test_pgt_books_a_call_back_after_the_email(env, monkeypatch):
    conn, ids = env["conn"], env["ids"]
    _all_hours(conn, ids["pgt"])
    slot = _pick(conn, ids["pgt"])
    seen = []
    _stub_model(monkeypatch, {"reply": "Booked!", "in_corpus": False, "handoff_ready": True,
                              "problem_summary": "Their support bot invents refund policies.",
                              "book": {**DANA, "email": "dana@biz.test", "slot": slot.id}}, seen)
    r = _pgt_ask(env["client"])
    body = r.json()
    assert "CALL-BACK TIMES" in seen[0] and slot.id in seen[0]
    assert body["booking"]["slot"] == slot.id
    assert body["reply"] == (
        f"Done, you're booked: Les will call you at 810-555-0142 on {slot.label}. "
        f"If anything changes, email him at {config.FOUNDER_EMAIL}.")
    assert [b["source"] for b in av.list_blocks(conn, ids["pgt"])] == ["booking"]
    assert av.list_blocks(conn, ids["alpha"]) == []
    leads = list_leads(conn, ids["pgt"])
    assert [(l["email"], l["phone"]) for l in leads] == [("dana@biz.test", "810-555-0142")]
    assert leads[0]["problem_summary"].startswith(f"Call-back booked for {slot.label}.")
    assert env["sent"][0]["to"] == ["les@pgt.test"]  # PGT has no notify_email: LEAD_INBOX


def test_pgt_never_books_without_the_email_first(env, monkeypatch):
    conn, ids = env["conn"], env["ids"]
    _all_hours(conn, ids["pgt"])
    slot = _pick(conn, ids["pgt"])
    _stub_model(monkeypatch, {"reply": "What's your email?", "in_corpus": False,
                              "handoff_ready": False, "problem_summary": None,
                              "book": {**DANA, "slot": slot.id}})  # no email
    body = _pgt_ask(env["client"]).json()
    assert body["booking"] is None and body["reply"] == "What's your email?"
    assert av.list_blocks(conn, ids["pgt"]) == []


def test_pgt_without_hours_is_the_email_only_assistant(env, monkeypatch):
    seen = []
    _stub_model(monkeypatch, {"reply": "Email Les.", "in_corpus": False, "handoff_ready": False,
                              "problem_summary": None}, seen)
    body = _pgt_ask(env["client"]).json()
    assert body["booking"] is None and body["reply"] == "Email Les."
    assert "CALL-BACK" not in seen[0]
    assert seen[0] == assistant._system_prompt()  # byte-identical to the pre-brick prompt


# --- tuning (2026-10-26 live proof): at most three times per reply, no em dashes ---------

def test_booking_prompts_cap_times_at_three():
    slots = "Tue Oct 27 (EDT): 2026-10-27T10:00, 2026-10-27T10:30"
    assert "Never list more than three times" in assistant._pgt_callback_section(slots)
    assert "Never list more than three times" in assistant._client_booking_rules("Acme", slots)


def test_pgt_reply_has_no_em_dashes(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        assistant, "_call_model",
        lambda system, turns: '"reply": "Sure \u2014 Les can call.", "in_corpus": false, "handoff_ready": false}',
    )
    r = assistant.respond([{"role": "user", "content": "hi"}])
    assert "\u2014" not in r.reply and r.reply == "Sure, Les can call."
