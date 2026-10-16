"""One-off: turn the executives' old error_of_order.xlsx into rows for the new 'errors' tab.

    python clean_history.py error_of_order.xlsx past_orders_extracted.csv history_cleaned.csv

- Packer, assembler and packing time are taken from the Samasya extract (TGS), not from what was typed.
- Only orders packed in 2026 are kept; the rest go to history_excluded.csv next to the output.
- Old error types are mapped to the new Internal / External / Unknown reasons and points are computed.
Then in the Google Sheet: 'errors' tab > File > Import > Upload > "Append to current sheet".
Filter the needs_review column and fix flagged rows by hand.
"""
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

import config as C


# ------------------------------------------------------------------ dates
def parse_complaint(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.strptime(re.sub(r"/+", "/", v.strip()), "%d/%m/%Y")
        except ValueError:
            return None
    return None


def parse_order_dt(v):
    if isinstance(v, datetime):
        return v
    for fmt in ("%d %B, %Y %I:%M:%S %p", "%d %B, %Y %I:%M %p"):
        try:
            return datetime.strptime(str(v).strip(), fmt)
        except ValueError:
            pass
    return None


def _swap(c):
    try:
        return c.replace(month=c.day, day=c.month)
    except ValueError:
        return None


def fix_report_date(c, o):
    """Excel often read dd/mm as mm/dd. A report comes 0-45 days after packing: keep the date if it fits,
    else try swapped day/month, then a one-year typo. If nothing fits, keep it and flag."""
    if c is None:
        return None, "report date unreadable"
    if o is None:
        return c, ""
    fits = lambda d: d is not None and 0 <= (d.date() - o.date()).days <= 45
    if fits(c):
        return c, ""
    sw = _swap(c)
    cands = [sw, c.replace(year=c.year + 1), c.replace(year=c.year - 1)]
    if sw:
        cands += [sw.replace(year=sw.year + 1), sw.replace(year=sw.year - 1)]
    for cand in cands:
        if fits(cand):
            return cand, f"date repaired from {c:%Y-%m-%d}"
    return c, f"report date {(c.date() - o.date()).days} days after packing - check"


# ------------------------------------------------------------------ old type -> (category, reason, note)
def classify(raw):
    t = str(raw or "").strip().lower().rstrip("-: ")
    if t in ("", "none", "nan"):
        return "", "", "error type blank - classify manually"
    if "tat breached" in t:
        return "", "", "case registered after TAT breached - classify manually"
    if "correctly packed" in t:
        return "External", "Packed correctly - footage checked", "check: old text mentions correctly packed"
    if t == "both":
        return "Internal", "Internal - reason not recorded (old data)", "old value 'Both' - check"
    if "internal and external" in t:
        return "Internal", "Missing quantity", "old value 'internal and external both' - check"
    if "label" in t:
        return "Internal", "Wrong label / wrong order labelled", ""
    if t.startswith("external"):
        return "External", "Packed correctly - footage checked", ""
    if t.startswith("internal"):
        return "Internal", "Internal - reason not recorded (old data)", ""
    if "did not open" in t:
        return "Internal", "Outer box not opened to check", ""
    if "p6" in t or "histor" in t:
        return "Unknown", "History not found", ""
    if "footage was not found" in t:
        return "Unknown", "Footage not found", ""
    if "not clear" in t:
        return "Unknown", "Footage not clear", ""
    if "strips" in t or "syrup" in t or "not brough" in t or "not been brought" in t:
        return "Unknown", "Items not visible (not taken out of box)", ""
    if "camera" in t:
        return "Unknown", "Packed / assembled out of camera view", ""
    return "", "", f"unrecognised error type: {raw}"


def main(xlsx, extract, dst):
    ws = pd.read_excel(xlsx, sheet_name="2026", header=0, usecols="A:G", dtype=object)
    ws.columns = ["complaint", "order_id", "issue", "dt", "packer", "assembler", "etype"]

    ex = pd.read_csv(extract, dtype=str)
    ex["ts"] = pd.to_datetime(ex["TGS"], errors="coerce")
    ex = ex[ex["ts"] >= "2025-10-01"].drop_duplicates("order_id").set_index("order_id")

    kept, excluded, mismatch = [], [], 0
    for r in ws.itertuples(index=False):
        if pd.isna(r.order_id):                       # month heading rows
            continue
        oid = str(int(float(r.order_id))) if str(r.order_id).replace(".0", "").isdigit() else str(r.order_id).strip()
        notes = []
        sheet_dt = parse_order_dt(r.dt)
        sp, sa = str(r.packer or "").strip().lower(), str(r.assembler or "").strip().lower()
        if oid in ex.index:
            e = ex.loc[oid]
            packed = e["ts"].to_pydatetime()
            p = str(e["packer"]).strip().lower() if pd.notna(e["packer"]) else sp
            a = str(e["assembler"]).strip().lower() if pd.notna(e["assembler"]) else sa
            if (p, a) != (sp, sa):
                mismatch += 1
                notes.append(f"names corrected from Samasya (sheet had packer={sp or '-'}, assembler={sa or '-'})")
        else:
            packed, p, a = sheet_dt, sp, sa
            notes.append("order not found in Samasya extract - names/time are as typed")
        if packed is not None and packed.year < 2026:
            excluded.append((oid, packed))
            continue
        rep, dnote = fix_report_date(parse_complaint(r.complaint), packed)
        cat, reason, cnote = classify(r.etype)
        notes += [x for x in (dnote, cnote) if x]
        pp, ap = C.points(cat, reason, 1) if cat else (0, 0)
        kept.append({
            "submitted_at": "", "logged_by": "imported",
            "how_caught": C.IMPORTED, "order_id": oid,
            "packed_at": packed.strftime("%Y-%m-%d %H:%M:%S") if packed else "",
            "packer": p, "assembler": a, "category": cat, "reason": reason,
            "drugs_affected": "", "mistakes": 1 if cat == "Internal" else 0,
            "packer_points": pp, "assembler_points": ap,
            "description": " ".join(str(r.issue or "").split()),
            "reversed": "", "reversed_reason": "", "reversed_on": "",
            "needs_review": "; ".join(notes),
        })
    df = pd.DataFrame(kept, columns=C.COLUMNS)
    df.to_csv(dst, index=False)
    pd.DataFrame(excluded, columns=["order_id", "packed_at"]).to_csv(Path(dst).with_name("history_excluded.csv"), index=False)
    print(f"{len(df)} rows kept (packed in 2026), {len(excluded)} excluded (packed before 2026)")
    print(f"{mismatch} rows had packer/assembler corrected from Samasya; {(df.needs_review != '').sum()} rows flagged")
    print(df.groupby("category").size().to_string())
    print("packer points", int(df.packer_points.sum()), "| assembler points", int(df.assembler_points.sum()))


if __name__ == "__main__":
    main(*sys.argv[1:4])
