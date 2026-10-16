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


_MISSING = {"", "nan", "none", "not mentioned", "-", "na", "n/a"}


def _missing(col):
    return col.astype(str).str.strip().str.lower().isin(_MISSING)


def score(df, rules=None):
    """Recalculate packer_points / assembler_points for every entry from the CURRENT points rules,
    so a change in Settings applies to the whole history, not only to new entries."""
    d = df.copy()
    pts = [C.points(c, r, m, rules) for c, r, m in zip(d["category"], d["reason"], d["mistakes"])]
    d["packer_points"] = [p for p, _ in pts]
    d["assembler_points"] = [a for _, a in pts]
    return d


def active(df):
    """Entries that count: not reversed, with a packing time and with BOTH a packer and an assembler named.
    Adds the packing date as `day`."""
    keep = (df["reversed"] != "Yes") & df["packed_at"].notna() & ~_missing(df["packer"]) & ~_missing(df["assembler"])
    a = df[keep].copy()
    a["day"] = a["packed_at"].dt.date
    return a


def _not_excluded(series, exclude):
    ex = {str(x).strip().lower() for x in exclude}
    return ~series.astype(str).str.strip().str.lower().isin(ex)


def _vol(vol):
    v = vol.copy()
    v["day"] = pd.to_datetime(v["day"]).dt.date
    return v


def person_table(act, vol, role, start, end, low_volume=C.LOW_VOLUME, exclude=C.EXCLUDED):
    """One row per person between two dates: orders, complaints, points, error %, accuracy %.
    People in `exclude` (executives, test logins) are left out."""
    col = f"{role}_points"
    a = act[(act["day"] >= start) & (act["day"] <= end)]
    pts = a.groupby(role).agg(points=(col, "sum"), complaints=(col, "size")).reset_index().rename(columns={role: "person"})
    v = _vol(vol)
    v = v[(v["role"] == role) & (v["day"] >= start) & (v["day"] <= end) & _not_excluded(v["person"], exclude)]
    v = v.groupby("person")["orders"].sum().reset_index()
    pts = pts[_not_excluded(pts["person"], exclude)]
    t = v.merge(pts, on="person", how="left").fillna({"points": 0, "complaints": 0})
    t["error %"] = (t["points"] / t["orders"] * 100).round(2)
    t["accuracy %"] = (100 - t["error %"]).round(2)
    t["name"] = t["person"].map(name_of)
    t["note"] = ["low volume" if o < low_volume else "" for o in t["orders"]]
    t = t[["name", "person", "orders", "complaints", "points", "error %", "accuracy %", "note"]]
    return t.sort_values("error %", ascending=False).reset_index(drop=True)


def team_error_pct(table):
    return float(table["points"].sum() / table["orders"].sum() * 100) if table["orders"].sum() else 0.0


def monthly_pivot(act, vol, role, start, end, min_orders=100, exclude=C.EXCLUDED):
    """Error % per person per month inside the date range (a part-month shows only the days in range)."""
    col = f"{role}_points"
    a = act[(act["day"] >= start) & (act["day"] <= end)].copy()
    a["month"] = pd.to_datetime(a["day"]).dt.strftime("%Y-%m")
    pts = a.groupby(["month", role])[col].sum().rename("points").reset_index().rename(columns={role: "person"})
    v = _vol(vol)
    pts = pts[_not_excluded(pts["person"], exclude)]
    v = v[(v["role"] == role) & (v["day"] >= start) & (v["day"] <= end) & _not_excluded(v["person"], exclude)].copy()
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
