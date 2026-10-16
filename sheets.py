"""Google Sheets storage via a service account.

Tabs: `errors` (one row per logged error), `settings` (the points rules saved from the app's Settings panel)
and `settings_log` (who changed the points, and when). The app creates `settings` / `settings_log` itself.
"""
import copy
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
import streamlit as st

import analysis
from config import COLUMNS, REASONS

TAB = "errors"
SETTINGS_TAB = "settings"
LOG_TAB = "settings_log"
SETTINGS_COLS = ["category", "reason", "packer_points", "assembler_points", "updated_by", "updated_at"]
LOG_COLS = ["changed_at", "changed_by", "changes"]
IST = ZoneInfo("Asia/Kolkata")


def _now() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")


@st.cache_resource(show_spinner=False)
def _book():
    gc = gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    return gc.open_by_key(st.secrets["sheet_id"])


@st.cache_resource(show_spinner=False)
def _tab():
    sh = _book()
    try:
        ws = sh.worksheet(TAB)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(TAB, rows=2000, cols=len(COLUMNS))
    head = ws.row_values(1)
    if not head:
        ws.update(range_name="A1", values=[COLUMNS])
    elif head != COLUMNS:
        raise RuntimeError(f"Header of tab '{TAB}' doesn't match the app's columns. Expected: {COLUMNS}")
    return ws


def append_error(row: dict):
    _tab().append_row([str(row.get(c, "") or "") for c in COLUMNS], value_input_option="USER_ENTERED")
    load_errors.clear()


@st.cache_data(ttl=60, show_spinner=False)
def load_errors() -> pd.DataFrame:
    recs = _tab().get_all_records(expected_headers=COLUMNS)
    df = pd.DataFrame(recs, columns=COLUMNS)
    df["sheet_row"] = df.index + 2                       # sheet row number, used for reversals
    df["order_id"] = df["order_id"].astype(str).str.strip()
    for c in ("packer_points", "assembler_points", "mistakes"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["packed_at"] = pd.to_datetime(df["packed_at"], errors="coerce")
    return df


def duplicates(order_id: str, reason: str, drugs: str) -> pd.DataFrame:
    return analysis.duplicates(load_errors(), order_id, reason, drugs)


def order_entries(order_id: str) -> pd.DataFrame:
    df = load_errors()
    return df[df["order_id"] == str(order_id).strip()]


def reverse_entry(sheet_row: int, reason: str):
    ws = _tab()
    c = COLUMNS.index("reversed") + 1
    ws.update(range_name=gspread.utils.rowcol_to_a1(sheet_row, c),
              values=[["Yes", reason, datetime.now(IST).strftime("%Y-%m-%d")]])
    load_errors.clear()


# ----------------------------------------------------------------- points rules (Settings panel)
def _num(v):
    v = float(v)
    return int(v) if v == int(v) else v


@st.cache_data(ttl=60, show_spinner=False)
def load_rules():
    """-> (rules, last_change). rules has the same shape as config.REASONS: the defaults with the saved points laid
    over them. last_change = (when, who) or None."""
    rules = copy.deepcopy(REASONS)
    book = _book()
    try:
        for r in book.worksheet(SETTINGS_TAB).get_all_records():
            cat, rs = str(r.get("category", "")), str(r.get("reason", ""))
            if cat in rules and rs in rules[cat]:
                for key, col in (("p", "packer_points"), ("a", "assembler_points")):
                    v = pd.to_numeric(r.get(col), errors="coerce")
                    if pd.notna(v) and v >= 0:
                        rules[cat][rs][key] = _num(v)
    except gspread.WorksheetNotFound:
        pass
    last = None
    try:
        rows = book.worksheet(LOG_TAB).get_all_values()
        if len(rows) > 1:
            last = (rows[-1][0], rows[-1][1])
    except gspread.WorksheetNotFound:
        pass
    return rules, last


def rules():
    """(rules, last_change). Never raises: if the sheet can't be read the original points are used."""
    try:
        return load_rules()
    except Exception:
        return copy.deepcopy(REASONS), None


def _get_or_make(name, cols):
    book = _book()
    try:
        return book.worksheet(name)
    except gspread.WorksheetNotFound:
        return book.add_worksheet(name, rows=200, cols=len(cols))


def save_rules(new_rules: dict, who: str):
    """Store the points rules in the `settings` tab and note the change in `settings_log`."""
    old, _ = load_rules()
    changes = []
    for cat, reasons in new_rules.items():
        for rs, v in reasons.items():
            o = old.get(cat, {}).get(rs, {})
            if (o.get("p"), o.get("a")) != (v["p"], v["a"]):
                changes.append(f"{rs}: packer {o.get('p')}->{v['p']}, assembler {o.get('a')}->{v['a']}")
    now = _now()
    rows = [SETTINGS_COLS] + [[cat, rs, v["p"], v["a"], who, now]
                              for cat, reasons in new_rules.items() for rs, v in reasons.items()]
    ws = _get_or_make(SETTINGS_TAB, SETTINGS_COLS)
    ws.clear()
    ws.update(range_name="A1", values=rows)
    log = _get_or_make(LOG_TAB, LOG_COLS)
    if not log.row_values(1):
        log.update(range_name="A1", values=[LOG_COLS])
    log.append_row([now, who, "; ".join(changes) or "saved, no change"], value_input_option="RAW")
    load_rules.clear()
    return changes
