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
    assert len(A.duplicates(df, "1", "Wrong drug packed", "")) == 0          # no drug given but the earlier one has some: ask, don't block
    assert len(A.unclear_duplicates(df, "1", "Wrong drug packed", "")) == 1
    df.loc[0, "reversed"] = "Yes"
    assert len(A.duplicates(df, "1", "Wrong drug packed", "DC 12")) == 0     # reversed entries don't block


def test_active_drops_reversed_and_unpacked():
    p = {"packer": "a@x.com", "assembler": "b@x.com"}
    df = _df([{"order_id": "1", "packed_at": "2026-03-02 10:00", **p},
              {"order_id": "2", "packed_at": "2026-03-03 10:00", "reversed": "Yes", **p},
              {"order_id": "3", "packed_at": "", **p}])
    assert list(A.active(df)["order_id"]) == ["1"]


def test_active_drops_entries_without_packer_or_assembler():
    df = _df([{"order_id": "1", "packed_at": "2026-03-02", "packer": "a@x.com", "assembler": "b@x.com"},
              {"order_id": "2", "packed_at": "2026-03-02", "packer": "", "assembler": "b@x.com"},
              {"order_id": "3", "packed_at": "2026-03-02", "packer": "a@x.com", "assembler": "not mentioned"},
              {"order_id": "4", "packed_at": "2026-03-02", "packer": "a@x.com", "assembler": "  "}])
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
    df = _df([{"order_id": "1", "packed_at": "2026-03-02", "packer": "naagard47@gmail.com", "assembler": "b@x.com", "packer_points": 1}])
    vol = _vol([("2026-03-02", "packer", "naagard47@gmail.com", 100)])
    r = A.person_table(A.active(df), vol, "packer", date(2026, 3, 1), date(2026, 3, 31)).iloc[0]
    assert r["note"] == "low volume" and r["name"] == "Deepak"
    assert A.name_of("someone.new@gmail.com") == "someone.new"


def test_monthly_pivot_and_team_pct():
    df = _df([{"order_id": "1", "packed_at": "2026-03-02", "packer": "a@x.com", "assembler": "b@x.com", "packer_points": 1},
              {"order_id": "2", "packed_at": "2026-04-02", "packer": "a@x.com", "assembler": "b@x.com", "packer_points": 2}])
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


def test_excluded_people_are_left_out_of_every_table():
    df = _df([{"order_id": "1", "packed_at": "2026-03-02", "packer": "a@x.com", "assembler": "dmg@saya.net.in", "assembler_points": 1},
              {"order_id": "2", "packed_at": "2026-03-02", "packer": "ANAschoudhary200084@gmail.com", "assembler": "b@x.com", "packer_points": 2}])
    vol = _vol([("2026-03-02", "packer", "a@x.com", 600), ("2026-03-02", "packer", "anaschoudhary200084@gmail.com", 600),
                ("2026-03-02", "assembler", "dmg@saya.net.in", 600), ("2026-03-02", "assembler", "b@x.com", 600)])
    act = A.active(df)
    s, e = date(2026, 3, 1), date(2026, 3, 31)
    assert list(A.person_table(act, vol, "packer", s, e)["person"]) == ["a@x.com"]
    assert list(A.person_table(act, vol, "assembler", s, e)["person"]) == ["b@x.com"]
    assert list(A.monthly_pivot(act, vol, "assembler", s, e).index) == ["b"]
    # the exclusion list can be overridden
    assert len(A.person_table(act, vol, "packer", s, e, exclude=())) == 2


def test_score_follows_the_current_rules_for_old_and_new_entries():
    df = _df([{"category": "Internal", "reason": "Wrong label / wrong order labelled", "mistakes": 1},
              {"category": "Internal", "reason": "Wrong drug packed", "mistakes": 3},
              {"category": "External", "reason": "Packed correctly - footage checked", "mistakes": 0}])
    base = A.score(df)
    assert list(base["packer_points"]) == [2, 3, 0] and list(base["assembler_points"]) == [0, 3, 0]
    import copy
    rules = copy.deepcopy(C.REASONS)
    rules["Internal"]["Wrong label / wrong order labelled"]["p"] = 3        # raise the label penalty
    rules["Internal"]["Wrong drug packed"]["a"] = 0.5                       # and halve the assembler's
    new = A.score(df, rules)
    assert list(new["packer_points"]) == [3, 3, 0] and list(new["assembler_points"]) == [0, 1.5, 0]
    assert C.points("Internal", "Wrong label / wrong order labelled", 4, rules) == (3, 0)   # still once per order
    assert A.score(df.iloc[0:0]).empty                                                      # empty log is fine


def test_entries_logged_before_the_order_exists_get_filled_in_later():
    df = _df([{"order_id": "1", "packed_at": "2026-03-02", "packer": "a@x.com", "assembler": "b@x.com"},      # complete
              {"order_id": "2", "packed_at": "", "packer": "", "assembler": ""},                              # found later
              {"order_id": "3", "packed_at": "", "packer": "c@x.com", "assembler": ""},                       # names partly typed
              {"order_id": "4", "packed_at": "", "packer": "", "assembler": ""},                              # typo, never found
              {"order_id": "5", "packed_at": "", "packer": "", "assembler": "", "reversed": "Yes"}])          # reversed: ignored
    assert A.unresolved_ids(df) == ("2", "3", "4")
    info = pd.DataFrame({"order_id": ["1", "2", "3"], "packer": ["zz@x.com", "p@x.com", "other@x.com"],
                         "assembler": ["zz@x.com", "q@x.com", "r@x.com"],
                         "packed_at": pd.to_datetime(["2026-01-01", "2026-03-05", "2026-03-06"])})
    out = A.fill_from_orders(df, info).set_index("order_id")
    assert out.loc["1", "packer"] == "a@x.com" and out.loc["1", "packed_at"] == pd.Timestamp("2026-03-02")   # never overwritten
    assert (out.loc["2", "packer"], out.loc["2", "assembler"], out.loc["2", "packed_at"]) == ("p@x.com", "q@x.com", pd.Timestamp("2026-03-05"))
    assert out.loc["3", "packer"] == "c@x.com" and out.loc["3", "assembler"] == "r@x.com"                    # keeps what was typed
    assert pd.isna(out.loc["4", "packed_at"]) and out.loc["4", "packer"] == ""                                 # still unknown
    assert A.unresolved_ids(A.fill_from_orders(df, info)) == ("4",)
    assert A.fill_from_orders(df, pd.DataFrame(columns=info.columns)).equals(df)                              # nothing found


def test_second_entry_on_the_same_order():
    none = _df([{"order_id": "1", "reason": "Wrong drug packed"}])                          # earlier entry names no drug
    assert len(A.duplicates(none, "1", "Wrong drug packed", "")) == 1                      # neither names a drug: same mistake, blocked
    assert len(A.duplicates(none, "1", "Wrong drug packed", "DC 55")) == 0                 # new one names a drug: not blocked...
    assert len(A.unclear_duplicates(none, "1", "Wrong drug packed", "DC 55")) == 1         # ...but the person confirms it is different
    assert len(A.unclear_duplicates(none, "1", "Wrong drug packed", "")) == 0
    assert len(A.duplicates(none, "1", "Packed correctly - footage checked", "")) == 0     # Internal then External: always fine
    assert len(A.unclear_duplicates(none, "1", "Packed correctly - footage checked", "")) == 0
    one = _df([{"order_id": "1", "reason": "Wrong drug packed", "drugs_affected": "DC 12"}])
    assert len(A.duplicates(one, "1", "Wrong drug packed", "DC 55")) == 0 and len(A.unclear_duplicates(one, "1", "Wrong drug packed", "DC 55")) == 0


def test_errors_count_on_logged_day_not_packed_day():
    import datetime as dt
    import pandas as pd
    import analysis as A
    df = pd.DataFrame({
        "submitted_at": ["2026-09-03 10:00:00", "2026-08-30", ""],
        "packed_at": pd.to_datetime(["2026-08-20", "2026-08-25", "2026-08-10"]),
        "packer": ["a@x.com", "a@x.com", ""], "assembler": ["b@x.com", "b@x.com", "b@x.com"],
        "reversed": ["", "", ""],
    })
    act = A.active(df)
    assert list(act["day"]) == [dt.date(2026, 9, 3), dt.date(2026, 8, 30)]
    assert len(A.uncounted(df)) == 1
