from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import analysis as A
import config as C
import db
import sheets

IST = ZoneInfo("Asia/Kolkata")


def fd(x, fmt="%d %b %Y"):
    """Format a date that may be missing."""
    return "-" if pd.isna(x) else x.strftime(fmt)


START = date.fromisoformat(C.START_DATE)
st.set_page_config(page_title="Order Error Log", page_icon="📦", layout="wide")


# ----------------------------------------------------------------- passcodes
def gate(secret_key: str, label: str, state_key: str, widget_key: str) -> bool:
    """True once the right passcode was entered (remembered for the session). No passcode set = open."""
    if st.session_state.get(state_key):
        return True
    expected = st.secrets.get(secret_key)
    if not expected:
        return True
    code = st.text_input(label, type="password", key=widget_key)
    if code:
        if code == expected:
            st.session_state[state_key] = True
            st.rerun()
        else:
            st.error("Wrong passcode.")
    return False


def date_range(key: str, label: str, lo: date, hi: date):
    """Presets + custom dates -> (start, end) inclusive, or None while the custom range is half-picked."""
    today = date.today()
    first = today.replace(day=1)
    presets = {"This month": (first, today),
               "Last month": ((first - timedelta(days=1)).replace(day=1), first - timedelta(days=1)),
               "Last 30 days": (today - timedelta(days=29), today),
               "Since 1 Jan 2026": (START, today), "Custom": None}
    c1, c2 = st.columns([1, 2])
    pick = c1.selectbox(label, list(presets), index=3, key=f"{key}_preset")
    if pick != "Custom":
        s, e = presets[pick]
        c2.caption(f"{s:%d %b %Y} to {e:%d %b %Y}")
        return max(s, lo), min(e, hi)
    rng = c2.date_input("From - To", value=(max(lo, today - timedelta(days=29)), min(hi, today)),
                        min_value=lo, max_value=hi, key=f"{key}_custom")
    if isinstance(rng, (tuple, list)) and len(rng) == 2:
        return rng[0], rng[1]
    st.info("Pick both the start and the end date.")
    return None


st.title("📦 Order Error Log")
if not gate("app_passcode", "Team passcode", "ok_app", "in_app"):
    st.stop()

tab_log, tab_stats, tab_logs = st.tabs(["Log an error", "Analytics", "Logs"])

# ================================================================= TAB 1: enter an error
with tab_log:
    _, mid, _ = st.columns([1, 2.4, 1])
    with mid:
        n = st.session_state.setdefault("form_n", 0)  # bumped after a save to clear the form
        if st.session_state.pop("just_saved", None):
            st.success(f"Saved order {st.session_state.pop('saved_id', '')}. You can log the next one.")

        order_id = st.text_input("Order ID", key=f"oid{n}", placeholder="e.g. 583492").strip()

        info = None
        if order_id and not order_id.isdigit():
            st.warning("Order ID should be numbers only.")
        elif order_id:
            try:
                with st.spinner("Looking up order…"):
                    info = db.lookup_order(order_id)
                if info is None:
                    st.warning("Order not found in Samasya. Enter the packer / assembler manually.")
            except Exception as e:  # never show secrets; never block logging because the database is down
                st.warning(f"Could not reach Samasya ({type(e).__name__}). Enter the packer / assembler manually.")

        prior = sheets.order_entries(order_id) if order_id.isdigit() else pd.DataFrame()
        if len(prior):
            st.info(f"{len(prior)} entr{'y' if len(prior) == 1 else 'ies'} already logged for this order: "
                    + "; ".join(f"{r.category} - {r.reason}" + (" (reversed)" if r.reversed == "Yes" else "")
                                for r in prior.itertuples()))

        c1, c2 = st.columns(2)
        packer = c1.text_input("Packer", value=(info or {}).get("packer") or "", key=f"p{n}{order_id}")
        assembler = c2.text_input("Assembler", value=(info or {}).get("assembler") or "", key=f"a{n}{order_id}")
        if info and info.get("packed_at"):
            st.caption(f"Packed: {info['packed_at']:%d %b %Y, %I:%M %p}"
                       + (f"  ·  {info['n_items']} item(s) on this order" if info.get("n_items") else ""))

        category = st.selectbox("Was it our error?", C.CATEGORIES, index=None,
                                placeholder="Internal / External / Unknown", key=f"cat{n}",
                                help="Internal = camera checked, we made the mistake. External = camera checked, we did not. "
                                     "Unknown = could not verify.")
        reason = st.selectbox("Specific reason", list(C.REASONS.get(category, {})), index=None, disabled=not category,
                              placeholder="Choose the type above first" if not category else "Choose…", key=f"rs{n}{category}")

        fixed = bool(category and reason and C.is_fixed(category, reason))
        max_n = (info or {}).get("n_items") or 50
        drugs = st.text_input("Drug code(s) affected", key=f"dc{n}", placeholder="e.g. DC 472, DC 1342",
                              help="Only the drugs that were wrong, not the whole order.")
        mistakes = 1
        if category == "Internal" and reason and not fixed:
            mistakes = st.number_input("Number of drugs / items wrong", 1, max_n, 1, key=f"mk{n}")
        if category and reason:
            pp, ap = C.points(category, reason, mistakes)
            st.caption(f"Effect on score: packer −{pp} · assembler −{ap}" if (pp or ap) else "No points deducted.")

        how = st.selectbox("How was it caught?", C.HOW_CAUGHT, index=None, placeholder="Choose…", key=f"hw{n}")
        desc = st.text_area("Describe what went wrong", key=f"ds{n}", height=100,
                            help="What the customer reported and what the camera showed.")
        execs = list(st.secrets.get("executives", []))
        logged_by = (st.selectbox("Logged by", execs, index=None, placeholder="Choose your name…", key=f"lb{n}")
                     if execs else st.text_input("Logged by", key=f"lb{n}"))

        if st.button("Submit", type="primary", use_container_width=True, key=f"submit{n}"):
            problems = []
            if not order_id.isdigit(): problems.append("Enter a valid Order ID.")
            if not category: problems.append("Choose Internal / External / Unknown.")
            elif not reason: problems.append("Choose the specific reason.")
            if not how: problems.append("Choose how it was caught.")
            if not desc.strip(): problems.append("Describe what went wrong.")
            if not logged_by: problems.append("Enter who is logging this.")
            if category == "Internal" and not (packer.strip() or assembler.strip()):
                problems.append("Packer / assembler missing.")
            if order_id.isdigit() and reason and len(sheets.duplicates(order_id, reason, drugs)):
                problems.append("This same mistake is already logged for this order. It counts once, so it was not added.")
            if problems:
                for p in problems: st.error(p)
            else:
                pp, ap = C.points(category, reason, mistakes)
                try:
                    sheets.append_error({
                        "submitted_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"),
                        "logged_by": logged_by, "how_caught": how,
                        "order_id": order_id,
                        "packed_at": f"{info['packed_at']:%Y-%m-%d %H:%M:%S}" if info and info.get("packed_at") else "",
                        "packer": packer.strip().lower(), "assembler": assembler.strip().lower(),
                        "category": category, "reason": reason, "drugs_affected": drugs.strip(),
                        "mistakes": 1 if fixed else mistakes, "packer_points": pp, "assembler_points": ap,
                        "description": desc.strip(),
                    })
                except Exception as e:
                    st.error(f"Could not save to the sheet ({type(e).__name__}). Nothing was lost; try again.")
                else:
                    st.session_state.update(form_n=n + 1, just_saved=True, saved_id=order_id)
                    st.rerun()

# ================================================================= TAB 2: analytics (admin)
with tab_stats:
    if gate("admin_passcode", "Admin passcode", "ok_admin", "in_admin_stats"):
        try:
            df, vol = sheets.load_errors(), db.load_volumes()
        except Exception as e:  # readable message, never the secrets
            st.error(f"Could not read the sheet or the database ({type(e).__name__}). Check the secrets and the access.")
            df = vol = None
        if vol is not None and vol.empty:
            st.info("No order volumes were returned from the database.")
        elif vol is not None:
            act = A.active(df)
            lo, hi = START, date.today()
            rng = date_range("an", "Packed in", lo, hi)
            if rng:
                s, e = rng
                tp, ta = A.person_table(act, vol, "packer", s, e), A.person_table(act, vol, "assembler", s, e)
                inx = act[(act["day"] >= s) & (act["day"] <= e)]
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Packer error %", f"{A.team_error_pct(tp):.2f}")
                m2.metric("Assembler error %", f"{A.team_error_pct(ta):.2f}")
                m3.metric("Internal entries", int((inx["category"] == "Internal").sum()))
                m4.metric("Unknown (no penalty)", int((inx["category"] == "Unknown").sum()))
                st.caption("Error % = points ÷ orders handled × 100, for orders packed in the chosen dates. A label error "
                           f"is 2 points; reversed entries are excluded. People with under {C.LOW_VOLUME} orders are marked low volume.")

                fmt = {"orders": "{:,.0f}", "complaints": "{:.0f}", "points": "{:.0f}", "error %": "{:.2f}", "accuracy %": "{:.2f}"}
                cl, cr = st.columns(2)
                cl.subheader("Packers")
                cl.dataframe(tp.drop(columns=["person"]).style.format(fmt), use_container_width=True, hide_index=True)
                cr.subheader("Assemblers")
                cr.dataframe(ta.drop(columns=["person"]).style.format(fmt), use_container_width=True, hide_index=True)

                st.subheader("Error % by month")
                role = st.radio("Role", ["packer", "assembler"], horizontal=True, key="an_role")
                st.dataframe(A.monthly_pivot(act, vol, role, s, e).style.format("{:.2f}", na_rep="-"), use_container_width=True)

                st.subheader("By reason")
                st.dataframe(inx.groupby(["category", "reason"]).agg(entries=("order_id", "size"), packer_points=("packer_points", "sum"),
                             assembler_points=("assembler_points", "sum")).reset_index().sort_values("entries", ascending=False),
                             use_container_width=True, hide_index=True)

# ================================================================= TAB 3: logs (admin) - read only, reversal only
with tab_logs:
    if gate("admin_passcode", "Admin passcode", "ok_admin", "in_admin_logs"):
        try:
            df = sheets.load_errors()
        except Exception as e:
            st.error(f"Could not read the sheet ({type(e).__name__}). Check the secrets and the access.")
            df = None
        if df is not None:
            f1, f2 = st.columns([1, 3])
            col = "packed_at"
            rng = date_range("lg", "Dates", START, date.today())
            if rng:
                s, e = rng
                s1, s2, s3 = st.columns([2, 1, 1])
                q = s1.text_input("Search", placeholder="order ID, person, reason, drug code, text…", key="lg_q")
                cat = s2.selectbox("Type", ["All"] + C.CATEGORIES, key="lg_cat")
                show_rev = s3.checkbox("Include reversed", value=True, key="lg_rev")
                d = df[(df[col].dt.date >= s) & (df[col].dt.date <= e)]
                if cat != "All": d = d[d["category"] == cat]
                if not show_rev: d = d[d["reversed"] != "Yes"]
                d = A.search(d, q).sort_values(col, ascending=False)
                st.caption(f"{len(d)} entr{'y' if len(d) == 1 else 'ies'} · read-only. Open one below to see everything about it.")
                view = d.assign(packer=d["packer"].map(A.name_of), assembler=d["assembler"].map(A.name_of))[
                    ["order_id", "packed_at", "category", "reason", "packer", "assembler", "mistakes",
                     "packer_points", "assembler_points", "reversed", "logged_by"]]
                st.dataframe(view, use_container_width=True, hide_index=True)
                st.download_button("Download these rows (CSV)", d.drop(columns=["sheet_row"]).to_csv(index=False).encode(),
                                   "order_errors.csv", "text/csv")

                st.subheader("Open an entry")
                labels = {int(r.sheet_row): f"{r.order_id} · {r.category} · {r.reason} · {A.name_of(r.packer) or '?'} / "
                                            f"{A.name_of(r.assembler) or '?'}" + (" · REVERSED" if r.reversed == "Yes" else "")
                          for r in d.head(500).itertuples()}
                pick = st.selectbox("Entry", list(labels), format_func=labels.get, index=None,
                                    placeholder="Choose, or type an order ID…", key="lg_pick")
                if pick is not None:
                    r = df[df["sheet_row"] == pick].iloc[0]
                    a, b = st.columns(2)
                    a.markdown(f"**Order** {r.order_id}  \n**Packed** {fd(r.packed_at, '%d %b %Y %H:%M')}  \n"
                               f"**Packer** {A.name_of(r.packer)} ({r.packer})  \n**Assembler** {A.name_of(r.assembler)} ({r.assembler})")
                    b.markdown(f"**Type** {r.category} - {r.reason}  \n**Drugs** {r.drugs_affected or '-'} · **mistakes** {int(r.mistakes)}  \n"
                               f"**Points** packer {int(r.packer_points)}, assembler {int(r.assembler_points)}  \n"
                               f"**Caught by** {r.how_caught}  \n"
                               f"**Logged by** {r.logged_by} at {r.submitted_at or '-'}")
                    st.markdown(f"**Description:** {r.description}")
                    if r.needs_review:
                        st.warning(f"Import note: {r.needs_review}")
                    if r.reversed == "Yes":
                        st.info(f"Reversed on {r.reversed_on}: {r.reversed_reason}. The entry stays here but its points do not count.")
                    else:
                        with st.form("lg_reverse", clear_on_submit=True):
                            why = st.text_input("Reason for reversing this entry (appeal accepted)")
                            if st.form_submit_button("Reverse this entry"):
                                if not why.strip():
                                    st.error("Write the reason first.")
                                else:
                                    sheets.reverse_entry(int(pick), why.strip())
                                    st.success("Reversed. The row stays in the log but no longer counts.")
                                    st.rerun()
