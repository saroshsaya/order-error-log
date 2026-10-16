"""Google Sheets storage via a service account."""
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
import streamlit as st

import analysis
from config import COLUMNS

TAB = "errors"


@st.cache_resource(show_spinner=False)
def _tab():
    gc = gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    sh = gc.open_by_key(st.secrets["sheet_id"])
    try:
        ws = sh.worksheet(TAB)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(TAB, rows=2000, cols=len(COLUMNS))
    head = ws.row_values(1)
    if not head:
        ws.update("A1", [COLUMNS])
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
    df["date_reported"] = pd.to_datetime(df["date_reported"], errors="coerce")
    return df


def duplicates(order_id: str, reason: str, drugs: str) -> pd.DataFrame:
    return analysis.duplicates(load_errors(), order_id, reason, drugs)


def order_entries(order_id: str) -> pd.DataFrame:
    df = load_errors()
    return df[df["order_id"] == str(order_id).strip()]


def reverse_entry(sheet_row: int, reason: str):
    ws = _tab()
    c = COLUMNS.index("reversed") + 1
    ws.update(gspread.utils.rowcol_to_a1(sheet_row, c), [["Yes", reason,
              datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")]])
    load_errors.clear()
