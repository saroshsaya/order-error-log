"""Numbers behind the Analytics and Logs tabs: pure pandas, no Streamlit, no database.

Error % = points / orders handled x 100, over orders PACKED between two dates (TGS).
vol = long table of orders handled: columns day (YYYY-MM-DD), role (packer / assembler), person, orders.
"""
import pandas as pd

import config as C


def name_of(login) -> str:
    login = str(login or "").strip().lower()
    return C.LOGIN_NAMES.get(login) or (login.split("@")[0] if login else "")


def _drugs(s):
    return {x.strip().lower() for x in str(s).replace(";", ",").split(",") if x.strip()}


def duplicates(df, order_id, reason, drugs):
    """Same order + same reason + overlapping drugs (or no drugs given) = the same mistake; it counts once."""
    d = df[(df["order_id"] == str(order_id).strip()) & (df["reason"] == reason) & (df["reversed"] != "Yes")]
    mine = _drugs(drugs)
    if not mine or d.empty:
        return d
    return d[[(not _drugs(r)) or bool(mine & _drugs(r)) for r in d["drugs_affected"]]]


def active(df):
    """Entries that count: not reversed and with a packing time. Adds the packing date as `day`."""
    a = df[(df["reversed"] != "Yes") & df["packed_at"].notna()].copy()
    a["day"] = a["packed_at"].dt.date
    return a


def _vol(vol):
    v = vol.copy()
    v["day"] = pd.to_datetime(v["day"]).dt.date
    return v


def person_table(act, vol, role, start, end, low_volume=C.LOW_VOLUME):
    """One row per person between two dates: orders, complaints, points, error %, accuracy %."""
    col = f"{role}_points"
    a = act[(act["day"] >= start) & (act["day"] <= end)]
    pts = a.groupby(role).agg(points=(col, "sum"), complaints=(col, "size")).reset_index().rename(columns={role: "person"})
    v = _vol(vol)
    v = v[(v["role"] == role) & (v["day"] >= start) & (v["day"] <= end)].groupby("person")["orders"].sum().reset_index()
    t = v.merge(pts, on="person", how="left").fillna({"points": 0, "complaints": 0})
    t["error %"] = (t["points"] / t["orders"] * 100).round(2)
    t["accuracy %"] = (100 - t["error %"]).round(2)
    t["name"] = t["person"].map(name_of)
    t["note"] = ["low volume" if o < low_volume else "" for o in t["orders"]]
    t = t[["name", "person", "orders", "complaints", "points", "error %", "accuracy %", "note"]]
    return t.sort_values("error %", ascending=False).reset_index(drop=True)


def team_error_pct(table):
    return float(table["points"].sum() / table["orders"].sum() * 100) if table["orders"].sum() else 0.0


def monthly_pivot(act, vol, role, start, end, min_orders=100):
    """Error % per person per month inside the date range (a part-month shows only the days in range)."""
    col = f"{role}_points"
    a = act[(act["day"] >= start) & (act["day"] <= end)].copy()
    a["month"] = pd.to_datetime(a["day"]).dt.strftime("%Y-%m")
    pts = a.groupby(["month", role])[col].sum().rename("points").reset_index().rename(columns={role: "person"})
    v = _vol(vol)
    v = v[(v["role"] == role) & (v["day"] >= start) & (v["day"] <= end)].copy()
    v["month"] = pd.to_datetime(v["day"]).dt.strftime("%Y-%m")
    v = v.groupby(["month", "person"])["orders"].sum().reset_index()
    m = v.merge(pts, on=["month", "person"], how="left").fillna({"points": 0})
    m = m[m["orders"] >= min_orders]
    m["error %"] = (m["points"] / m["orders"] * 100).round(2)
    m["name"] = m["person"].map(name_of)
    return m.pivot(index="name", columns="month", values="error %")


def search(df, text):
    """Case-insensitive match on order id, people (login or display name), reason, drugs, description, logged by."""
    t = str(text or "").strip().lower()
    if not t:
        return df
    hay = (df["order_id"].astype(str) + " " + df["packer"] + " " + df["assembler"] + " "
           + df["packer"].map(name_of) + " " + df["assembler"].map(name_of) + " " + df["reason"] + " "
           + df["category"] + " " + df["drugs_affected"].astype(str) + " " + df["description"] + " "
           + df["logged_by"]).str.lower()
    return df[hay.str.contains(t, regex=False)]
