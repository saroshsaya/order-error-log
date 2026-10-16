"""Tests for the numbers behind the Analytics and Logs tabs (tiny synthetic data)."""
from datetime import date

import pandas as pd
import pytest

import analysis as A
import config as C


def _df(rows):
    d = pd.DataFrame([{**{c: "" for c in C.COLUMNS}, **r} for r in rows], columns=C.COLUMNS)
    d["packed_at"] = pd.to_datetime(d["packed_at"], errors="coerce")
    for c in ("packer_points", "assembler_points", "mistakes"):
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
    return d


def _vol(rows):
    return pd.DataFrame(rows, columns=["day", "role", "person", "orders"])


def test_points_rules():
    assert C.points("Internal", "Wrong drug packed", 2) == (2, 2)                   # (packer, assembler)
    assert C.points("Internal", "Wrong label / wrong order labelled", 5) == (2, 0)  # label: once per order, packer only
    assert C.points("Internal", "Assembly error caught by packer at packing", 3) == (0, 3)
    assert C.points("External", "Packed correctly - footage checked", 4) == (0, 0)
    assert C.points("Unknown", "Footage not found", 4) == (0, 0)
    assert C.points("Internal", "Wrong drug packed", 0) == (1, 1)


def test_same_person_stacks_to_four_points():
    wd_p, wd_a = C.points("Internal", "Wrong drug packed", 1)
    lb_p, lb_a = C.points("Internal", "Wrong label / wrong order labelled", 1)
    assert (wd_p + wd_a) + (lb_p + lb_a) == 4


def test_duplicates_same_mistake_counts_once():
    df = _df([{"order_id": "1", "reason": "Wrong drug packed", "drugs_affected": "DC 12"}])
    assert len(A.duplicates(df, "1", "Wrong drug packed", "dc 12")) == 1
    assert len(A.duplicates(df, "1", "Wrong drug packed", "DC 99")) == 0     # different drug = new mistake
    assert len(A.duplicates(df, "1", "Missing quantity", "DC 12")) == 0      # different reason = new mistake
    assert len(A.duplicates(df, "1", "Wrong drug packed", "")) == 1          # no drug given = same mistake
    df.loc[0, "reversed"] = "Yes"
    assert len(A.duplicates(df, "1", "Wrong drug packed", "DC 12")) == 0     # reversed entries don't block


def test_active_drops_reversed_and_unpacked():
    df = _df([{"order_id": "1", "packed_at": "2026-03-02 10:00"},
              {"order_id": "2", "packed_at": "2026-03-03 10:00", "reversed": "Yes"},
              {"order_id": "3", "packed_at": ""}])
    assert list(A.active(df)["order_id"]) == ["1"]


def test_error_percent_respects_the_date_range():
    df = _df([{"order_id": "1", "packed_at": "2026-03-02", "packer": "a@x.com", "assembler": "b@x.com", "packer_points": 2},
              {"order_id": "2", "packed_at": "2026-03-20", "packer": "a@x.com", "assembler": "b@x.com", "packer_points": 1, "assembler_points": 1},
              {"order_id": "3", "packed_at": "2026-04-05", "packer": "a@x.com", "assembler": "b@x.com", "packer_points": 5, "assembler_points": 5}])
    vol = _vol([("2026-03-02", "packer", "a@x.com", 400), ("2026-03-20", "packer", "a@x.com", 600), ("2026-04-05", "packer", "a@x.com", 1000),
                ("2026-03-02", "assembler", "b@x.com", 500)])
    act = A.active(df)
    march = A.person_table(act, vol, "packer", date(2026, 3, 1), date(2026, 3, 31)).iloc[0]
    assert (march["points"], march["orders"], march["error %"], march["accuracy %"]) == (3, 1000, 0.30, 99.70)
    first_half = A.person_table(act, vol, "packer", date(2026, 3, 1), date(2026, 3, 10)).iloc[0]
    assert (first_half["points"], first_half["orders"], first_half["error %"]) == (2, 400, 0.5)
    both = A.person_table(act, vol, "packer", date(2026, 3, 1), date(2026, 4, 30)).iloc[0]
    assert both["error %"] == pytest.approx(0.4)                                            # 8 / 2000
    asm = A.person_table(act, vol, "assembler", date(2026, 3, 1), date(2026, 3, 31)).iloc[0]
    assert asm["points"] == 1 and asm["error %"] == pytest.approx(0.2)                      # 1 / 500


def test_low_volume_and_names():
    df = _df([{"order_id": "1", "packed_at": "2026-03-02", "packer": "naagard47@gmail.com", "packer_points": 1}])
    vol = _vol([("2026-03-02", "packer", "naagard47@gmail.com", 100)])
    r = A.person_table(A.active(df), vol, "packer", date(2026, 3, 1), date(2026, 3, 31)).iloc[0]
    assert r["note"] == "low volume" and r["name"] == "Deepak"
    assert A.name_of("someone.new@gmail.com") == "someone.new"


def test_monthly_pivot_and_team_pct():
    df = _df([{"order_id": "1", "packed_at": "2026-03-02", "packer": "a@x.com", "packer_points": 1},
              {"order_id": "2", "packed_at": "2026-04-02", "packer": "a@x.com", "packer_points": 2}])
    vol = _vol([("2026-03-02", "packer", "a@x.com", 200), ("2026-04-02", "packer", "a@x.com", 400)])
    p = A.monthly_pivot(A.active(df), vol, "packer", date(2026, 3, 1), date(2026, 4, 30))
    assert p.loc["a", "2026-03"] == 0.5 and p.loc["a", "2026-04"] == 0.5
    t = A.person_table(A.active(df), vol, "packer", date(2026, 3, 1), date(2026, 4, 30))
    assert A.team_error_pct(t) == pytest.approx(0.5)                                         # 3 / 600


def test_search():
    df = _df([{"order_id": "583492", "packer": "naagard47@gmail.com", "assembler": "x@y.com", "reason": "Missing quantity", "description": "DC 12 missing"},
              {"order_id": "111", "packer": "lexor0001@gmail.com", "assembler": "x@y.com", "reason": "Wrong drug packed", "description": "wrong"}])
    assert list(A.search(df, "583492")["order_id"]) == ["583492"]
    assert list(A.search(df, "deepak")["order_id"]) == ["583492"]           # by display name
    assert list(A.search(df, "dc 12")["order_id"]) == ["583492"]
    assert len(A.search(df, "")) == 2
