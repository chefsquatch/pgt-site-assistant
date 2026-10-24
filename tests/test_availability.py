"""BRICK 5 — the availability store: the admin edits the schedule; it lives as data (F2).

Three layers, each proven separately:
  * the deterministic read (compute_open_windows) — pure, no DB: weekday mapping, blocks
    split windows, DST keeps wall-clock times, same inputs -> same output;
  * the wall (F1) + defense in depth (F6) on all three new scoped tables — isolation
    holds, is watched to go red with RLS disabled, and the app's own reads/deletes still
    isolate because they filter tenant_id in SQL;
  * the guarded admin endpoints (served behavior): 401 unauthed, edit -> read back,
    bad input -> 400, the open-windows preview reflects edits.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app import availability as av
from test_admin_endpoints import ADMIN_EMAIL, ADMIN_PASSWORD, client  # noqa: F401 (fixture)

DET = "America/Detroit"
TZ = ZoneInfo(DET)


def _w(weekday, start, end):
    return {"weekday": weekday, "start": start, "end": end}


def _spans(wins):
    return [(w.start.strftime("%Y-%m-%d %H:%M"), w.end.strftime("%H:%M")) for w in wins]


# --- the deterministic read (pure) ------------------------------------------------------

def test_weekday_zero_is_sunday():
    # 2026-10-25 is a Sunday; a weekday-0 window lands on it and nowhere else that week.
    wins = av.compute_open_windows([_w(0, "10:00", "12:00")], [], DET, date(2026, 10, 19), 7)
    assert _spans(wins) == [("2026-10-25 10:00", "12:00")]


def test_block_splits_a_window():
    # Tue 2026-10-27 09:00-17:00, blocked 12:00-13:00 local -> two open pieces.
    block = (datetime(2026, 10, 27, 12, 0, tzinfo=TZ), datetime(2026, 10, 27, 13, 0, tzinfo=TZ))
    wins = av.compute_open_windows([_w(2, "09:00", "17:00")], [block], DET, date(2026, 10, 27), 1)
    assert _spans(wins) == [("2026-10-27 09:00", "12:00"), ("2026-10-27 13:00", "17:00")]


def test_block_covering_the_whole_day_leaves_nothing():
    block = (datetime(2026, 10, 27, 0, 0, tzinfo=TZ), datetime(2026, 10, 28, 0, 0, tzinfo=TZ))
    assert av.compute_open_windows([_w(2, "09:00", "17:00")], [block], DET, date(2026, 10, 27), 1) == []


def test_block_in_another_zone_is_compared_as_an_instant():
    # 16:00-17:00 UTC == 12:00-13:00 EDT on 2026-10-27: same split as the local block.
    utc = ZoneInfo("UTC")
    block = (datetime(2026, 10, 27, 16, 0, tzinfo=utc), datetime(2026, 10, 27, 17, 0, tzinfo=utc))
    wins = av.compute_open_windows([_w(2, "09:00", "17:00")], [block], DET, date(2026, 10, 27), 1)
    assert _spans(wins) == [("2026-10-27 09:00", "12:00"), ("2026-10-27 13:00", "17:00")]


def test_dst_change_keeps_wall_clock_time():
    # DST ends 2026-11-01 in Detroit. A 09:00 Mon window is 09:00 local on both sides,
    # so its UTC offset moves from -4 to -5.
    wins = av.compute_open_windows([_w(1, "09:00", "10:00")], [], DET, date(2026, 10, 26), 8)
    assert [w.start.strftime("%H:%M") for w in wins] == ["09:00", "09:00"]
    assert [w.start.utcoffset().total_seconds() / 3600 for w in wins] == [-4.0, -5.0]


def test_same_inputs_same_output():
    args = ([_w(2, "09:00", "17:00"), _w(4, "13:00", "15:00")], [], DET, date(2026, 10, 25), 14)
    assert av.compute_open_windows(*args) == av.compute_open_windows(*args)


def test_input_validation():
    with pytest.raises(av.AvailabilityError):
        av.parse_hhmm("9am")
    with pytest.raises(av.AvailabilityError):
        av.validate_timezone("Mars/Olympus")
    assert av.validate_timezone(" America/Detroit ") == DET


# --- the wall (F1) + defense in depth (F6) on the three new tables ------------------------

def _seed(t):
    av.set_timezone(t.conn, t.A, "America/New_York")
    av.set_timezone(t.conn, t.B, "America/Chicago")
    a_win = av.add_window(t.conn, t.A, weekday=2, start="09:00", end="12:00", label="A hours")
    b_win = av.add_window(t.conn, t.B, weekday=2, start="13:00", end="17:00", label="B hours")
    a_blk = av.add_block(
        t.conn, t.A,
        starts_at=datetime(2026, 10, 27, 10, 0, tzinfo=TZ),
        ends_at=datetime(2026, 10, 27, 11, 0, tzinfo=TZ),
        reason="A dentist",
    )
    b_blk = av.add_block(
        t.conn, t.B,
        starts_at=datetime(2026, 10, 27, 14, 0, tzinfo=TZ),
        ends_at=datetime(2026, 10, 27, 15, 0, tzinfo=TZ),
        reason="B meeting",
    )
    return a_win, b_win, a_blk, b_blk


def _assert_isolated(t, b_win, b_blk):
    assert av.get_timezone(t.conn, t.A) == "America/New_York"
    assert [w["label"] for w in av.list_windows(t.conn, t.A)] == ["A hours"]
    assert [b["reason"] for b in av.list_blocks(t.conn, t.A)] == ["A dentist"]
    # A cannot delete B's rows — the id is real, but not A's.
    assert av.delete_window(t.conn, t.A, b_win) is False
    assert av.delete_block(t.conn, t.A, b_blk) is False
    assert [w["label"] for w in av.list_windows(t.conn, t.B)] == ["B hours"]
    assert [b["reason"] for b in av.list_blocks(t.conn, t.B)] == ["B meeting"]


def test_availability_is_tenant_scoped(tenants):
    _, b_win, _, b_blk = _seed(tenants)
    _assert_isolated(tenants, b_win, b_blk)


@pytest.mark.parametrize(
    "table", ["availability_settings", "availability_window", "availability_block"]
)
def test_red_control_raw_read_leaks_but_reads_isolate(tenants, table):
    _, b_win, _, b_blk = _seed(tenants)

    # RLS on, no tenant context: an unscoped read sees nothing (safe default).
    assert tenants.conn.execute(f'SELECT count(*) FROM "{table}";').fetchone()[0] == 0

    # Pull the wall down — the real prod BYPASSRLS condition. The raw read leaks BOTH.
    tenants.as_owner(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY;')
    assert tenants.conn.execute(f'SELECT count(*) FROM "{table}";').fetchone()[0] == 2  # the leak

    # The app's reads + deletes filter tenant_id in SQL (F6), so they STILL isolate.
    _assert_isolated(tenants, b_win, b_blk)

    tenants.as_owner(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;')
    tenants.as_owner(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY;')


def test_open_windows_reads_only_this_tenants_store(tenants):
    _seed(tenants)
    wins = av.open_windows(tenants.conn, tenants.A, start_date=date(2026, 10, 27), days=1)
    # A: Tue 09:00-12:00 New York, minus A's 10:00-11:00 Detroit (same zone offset) block.
    # B's 13:00-17:00 window and B's block never appear.
    assert _spans(wins) == [("2026-10-27 09:00", "10:00"), ("2026-10-27 11:00", "12:00")]


def test_unknown_tenant_settings_default_timezone(tenants):
    assert av.get_timezone(tenants.conn, tenants.A) == av.DEFAULT_TIMEZONE


def test_store_rejects_bad_rows(tenants):
    with pytest.raises(av.AvailabilityError):
        av.add_window(tenants.conn, tenants.A, weekday=7, start="09:00", end="10:00")
    with pytest.raises(av.AvailabilityError):
        av.add_window(tenants.conn, tenants.A, weekday=1, start="10:00", end="09:00")
    with pytest.raises(av.AvailabilityError):
        av.add_block(
            tenants.conn, tenants.A,
            starts_at=datetime(2026, 10, 27, 11, 0, tzinfo=TZ),
            ends_at=datetime(2026, 10, 27, 10, 0, tzinfo=TZ),
        )
    assert av.delete_window(tenants.conn, tenants.A, "not-a-uuid") is False


# --- the guarded endpoints (served behavior) ----------------------------------------------

def _login(c):
    r = c.post("/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200


def test_availability_endpoints_require_admin(client):  # noqa: F811
    assert client.get("/admin/availability").status_code == 401
    assert client.post("/admin/availability/windows", json={"weekday": 1, "start": "09:00", "end": "10:00"}).status_code == 401
    assert client.get("/admin/availability/open").status_code == 401


def test_admin_edits_availability_and_reads_it_back(client):  # noqa: F811
    _login(client)
    assert client.get("/admin/availability").json() == {
        "timezone": av.DEFAULT_TIMEZONE, "windows": [], "blocks": []
    }

    assert client.put("/admin/availability/timezone", json={"timezone": "America/Chicago"}).json()["timezone"] == "America/Chicago"
    wid = client.post(
        "/admin/availability/windows", json={"weekday": 2, "start": "09:00", "end": "17:00", "label": "Office"}
    ).json()["id"]
    bid = client.post(
        "/admin/availability/blocks",
        json={"starts_at": "2026-10-27T12:00", "ends_at": "2026-10-27T13:00", "reason": "Lunch"},
    ).json()["id"]

    view = client.get("/admin/availability").json()
    assert view["timezone"] == "America/Chicago"
    assert view["windows"] == [{"id": wid, "weekday": 2, "start": "09:00", "end": "17:00", "label": "Office"}]
    # The block was entered as wall time in the tenant's zone and comes back in it
    # (Chicago, CDT = -05:00) whatever zone the database session runs in.
    assert view["blocks"][0]["starts_at"] == "2026-10-27T12:00:00-05:00"
    assert view["blocks"][0]["ends_at"] == "2026-10-27T13:00:00-05:00"
    assert view["blocks"][0]["reason"] == "Lunch" and view["blocks"][0]["source"] == "manual"

    assert client.delete(f"/admin/availability/blocks/{bid}").status_code == 200
    assert client.delete(f"/admin/availability/windows/{wid}").status_code == 200
    assert client.delete(f"/admin/availability/windows/{wid}").status_code == 404
    assert client.get("/admin/availability").json()["windows"] == []


def test_bad_input_is_400_with_a_reason(client):  # noqa: F811
    _login(client)
    r = client.put("/admin/availability/timezone", json={"timezone": "Nowhere/Land"})
    assert r.status_code == 400 and "timezone" in r.json()["detail"]
    r = client.post("/admin/availability/windows", json={"weekday": 1, "start": "17:00", "end": "09:00"})
    assert r.status_code == 400 and "after start" in r.json()["detail"]
    r = client.post("/admin/availability/blocks", json={"starts_at": "tomorrow", "ends_at": "later"})
    assert r.status_code == 400
    assert client.get("/admin/availability/open?days=999").status_code == 400


def test_open_preview_reflects_the_edits(client):  # noqa: F811
    _login(client)
    client.post("/admin/availability/windows", json={"weekday": 0, "start": "10:00", "end": "11:00"})
    client.post("/admin/availability/windows", json={"weekday": 3, "start": "10:00", "end": "11:00"})
    opened = client.get("/admin/availability/open?days=7").json()["open"]
    # Seven consecutive days contain exactly one Sunday and one Wednesday.
    assert len(opened) == 2
    assert all(w["start"][11:16] == "10:00" and w["end"][11:16] == "11:00" for w in opened)
