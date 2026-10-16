import copy
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import altair as alt
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
st.set_page_config(page_title="Order Error Log", page_icon="📦", layout="wide", initial_sidebar_state="collapsed")


# ----------------------------------------------------------------- passcodes (only used if a passcode secret is set)
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


# ----------------------------------------------------------------- date filter with a Load button
def date_range(key: str, label: str, lo: date, hi: date):
    """Presets + custom dates -> (start, end) inclusive, or None until a period is chosen."""
    today = date.today()
    first = today.replace(day=1)
    presets = {"This month": (first, today),
               "Last month": ((first - timedelta(days=1)).replace(day=1), first - timedelta(days=1)),
               "Last 30 days": (today - timedelta(days=29), today),
               "Since 1 Jan 2026": (START, today), "Custom": None}
    c1, c2 = st.columns([1, 2])
    pick = c1.selectbox(label, list(presets), index=None, placeholder="Choose a period…", key=f"{key}_preset")
    if pick is None:
        c2.caption("Choose a period, then click Load.")
        return None
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


def load_range(key: str, label: str):
    """Date choice + a Load button. Returns the (start, end) that was last LOADED, or None."""
    rng = date_range(key, label, START, date.today())
    if st.button("Load", type="primary", key=f"{key}_load", disabled=rng is None):
        st.session_state[f"{key}_loaded"] = rng
    loaded = st.session_state.get(f"{key}_loaded")
    if loaded and rng and loaded != rng:
        st.caption("You changed the dates. Click Load to update.")
    return loaded


# ----------------------------------------------------------------- accuracy chart
def accuracy_chart(t: pd.DataFrame, title: str):
    """Horizontal bars of accuracy % per person, lowest on top. The axis is zoomed in (it does not start at 0)
    because almost everyone is above 98%, which would make plain bars look identical."""
    if t.empty:
        st.info("Nobody to show.")
        return
    lo = max(0, math.floor(t["accuracy %"].min()) - 1)
    base = alt.Chart(t).encode(
        y=alt.Y("name:N", sort=alt.EncodingSortField("accuracy %", order="ascending"), title=None,
                axis=alt.Axis(labelLimit=160)),
        x=alt.X("accuracy %:Q", scale=alt.Scale(domain=[lo, 100], clamp=True), title="Accuracy %"),
        tooltip=[alt.Tooltip("name:N", title="Name"), alt.Tooltip("orders:Q", title="Orders", format=","),
                 alt.Tooltip("points:Q", title="Points", format="g"), alt.Tooltip("error %:Q", format=".2f"),
                 alt.Tooltip("accuracy %:Q", format=".2f")])
    bars = base.mark_bar().encode(color=alt.condition(alt.datum.note == "low volume", alt.value("#757575"), alt.value("#2f6fb0")))
    labels = base.mark_text(align="right", dx=-5, color="white", fontWeight="bold").encode(text=alt.Text("accuracy %:Q", format=".2f"))
    st.subheader(title)
    st.altair_chart((bars + labels).properties(height=max(110, 30 * len(t))), use_container_width=True)
    st.caption(f"The axis starts at {lo}%, not 0, so the differences are visible.")


# ----------------------------------------------------------------- points rules + Settings panel
st.title("📦 Order Error Log")
if not gate("app_passcode", "Team passcode", "ok_app", "in_app"):
    st.stop()

RULES, LAST_CHANGE = sheets.rules()
EXECS = list(st.secrets.get("executives", []))


def _who(key):
    return (st.selectbox("Changed by", EXECS, index=None, placeholder="Choose your name…", key=key)
            if EXECS else st.text_input("Changed by", key=key))


with st.sidebar:
    st.header("Settings")
    st.caption("Points taken off for each internal error. A change applies to ALL entries in Analytics, old and new.")
    if LAST_CHANGE:
        st.caption(f"Last changed {LAST_CHANGE[0]} by {LAST_CHANGE[1]}.")
    if st.session_state.pop("set_saved", None):
        st.success("Saved.")
    ver = st.session_state.setdefault("set_v", 0)
    table = pd.DataFrame([{"Reason": rs, "Packer": v["p"], "Assembler": v["a"]}
                          for rs, v in RULES["Internal"].items()])
    edited = st.data_editor(
        table, hide_index=True, use_container_width=True, key=f"rules_ed{ver}", disabled=["Reason"],
        column_config={"Reason": st.column_config.TextColumn(width="medium"),
                       "Packer": st.column_config.NumberColumn("Packer", min_value=0, max_value=20, step=0.5, format="%g", required=True),
                       "Assembler": st.column_config.NumberColumn("Assembler", min_value=0, max_value=20, step=0.5, format="%g", required=True)})
    fixed_names = [rs for rs, v in RULES["Internal"].items() if v.get("fixed")]
    st.caption("Points are per wrong drug, except " + " and ".join(f"“{x}”" for x in fixed_names) + ", which count once per order. "
               "External and Unknown never take points.")
    set_who = _who("set_who")
    b1, b2 = st.columns(2)
    save, reset = b1.button("Save", type="primary", key="set_save", use_container_width=True), \
        b2.button("Reset", key="set_reset", use_container_width=True, help="Go back to the original points.")
    if save or reset:
        if not set_who:
            st.error("Choose your name first.")
        else:
            new = copy.deepcopy(C.REASONS if reset else RULES)
            if save:
                for r in edited.itertuples():
                    if pd.notna(r.Packer): new["Internal"][r.Reason]["p"] = sheets._num(r.Packer)
                    if pd.notna(r.Assembler): new["Internal"][r.Reason]["a"] = sheets._num(r.Assembler)
            try:
                sheets.save_rules(new, set_who)
            except Exception as e:
                st.error(f"Could not save ({type(e).__name__}). Try again.")
            else:
                st.session_state.update(set_saved=True, set_v=ver + 1)
                st.rerun()

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
                    st.warning("Order not found in Samasya. Check the order ID for a typo, or enter the packer / assembler below.")
            except Exception as e:  # never show secrets; never block logging because the database is down
                st.warning(f"Could not reach Samasya ({type(e).__name__}). Enter the packer / assembler below.")

        prior = sheets.order_entries(order_id) if order_id.isdigit() else pd.DataFrame()
        if len(prior):
            st.info(f"{len(prior)} entr{'y' if len(prior) == 1 else 'ies'} already logged for this order: "
                    + "; ".join(f"{r.category} - {r.reason}" + (" (reversed)" if r.reversed == "Yes" else "")
                                for r in prior.itertuples()))

        c1, c2 = st.columns(2)
        if info:   # found in Samasya: filled automatically, nothing to type
            packer = (info.get("packer") or "").strip()
            assembler = (info.get("assembler") or "").strip()
            c1.markdown(f"**Packer**  \n{A.name_of(packer) or packer or '-'}")
            c2.markdown(f"**Assembler**  \n{A.name_of(assembler) or assembler or '-'}")
        elif order_id.isdigit():   # not found (typo, or Samasya unreachable): allow typing them
            packer = c1.text_input("Packer (login email)", key=f"p{n}{order_id}").strip()
            assembler = c2.text_input("Assembler (login email)", key=f"a{n}{order_id}").strip()
        else:
            packer = assembler = ""
        if info and info.get("packed_at"):
            st.caption(f"Packed: {info['packed_at']:%d %b %Y, %I:%M %p}"
                       + (f"  ·  {info['n_items']} item(s) on this order" if info.get("n_items") else ""))

        category = st.selectbox("Was it our error?", C.CATEGORIES, index=None,
                                placeholder="Internal / External / Unknown", key=f"cat{n}",
                                help="Internal = camera checked, we made the mistake. External = camera checked, we did not. "
                                     "Unknown = could not verify.")
        reason = st.selectbox("Specific reason", list(RULES.get(category, {})), index=None, disabled=not category,
                              placeholder="Choose the type above first" if not category else "Choose…", key=f"rs{n}{category}")

        fixed = bool(category and reason and C.is_fixed(category, reason, RULES))
        max_n = (info or {}).get("n_items") or 50
        drugs = st.text_input("Drug code(s) affected", key=f"dc{n}", placeholder="e.g. DC 472, DC 1342",
                              help="Only the drugs that were wrong, not the whole order.")
        mistakes = 1
        if category == "Internal" and reason and not fixed:
            mistakes = st.number_input("Number of drugs / items wrong", 1, max_n, 1, key=f"mk{n}")
        if category and reason:
            pp, ap = C.points(category, reason, mistakes, RULES)
            st.caption(f"Effect on score: packer −{pp:g} · assembler −{ap:g}" if (pp or ap) else "No points deducted.")

        how = st.selectbox("How was it caught?", C.HOW_CAUGHT, index=None, placeholder="Choose…", key=f"hw{n}")
        desc = st.text_area("Describe what went wrong", key=f"ds{n}", height=100,
                            help="What the customer reported and what the camera showed.")
        logged_by = (st.selectbox("Logged by", EXECS, index=None, placeholder="Choose your name…", key=f"lb{n}")
                     if EXECS else st.text_input("Logged by", key=f"lb{n}"))

        if st.button("Submit", type="primary", use_container_width=True, key=f"submit{n}"):
            problems = []
            if not order_id.isdigit(): problems.append("Enter a valid Order ID.")
            if not category: problems.append("Choose Internal / External / Unknown.")
            elif not reason: problems.append("Choose the specific reason.")
            if not how: problems.append("Choose how it was caught.")
            if not desc.strip(): problems.append("Describe what went wrong.")
            if not logged_by: problems.append("Enter who is logging this.")
            if category == "Internal" and not (packer or assembler):
                problems.append("Packer / assembler missing.")
            if order_id.isdigit() and reason and len(sheets.duplicates(order_id, reason, drugs)):
                problems.append("This same mistake is already logged for this order. It counts once, so it was not added.")
            if problems:
                for p in problems: st.error(p)
            else:
                pp, ap = C.points(category, reason, mistakes, RULES)
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

# ================================================================= TAB 2: analytics
with tab_stats:
    if gate("admin_passcode", "Admin passcode", "ok_admin", "in_admin_stats"):
        loaded = load_range("an", "Packed in")
        if loaded:
            s, e = loaded
            try:
                df, vol = A.score(sheets.load_errors(), RULES), db.load_volumes(s, e)
            except Exception as ex:  # readable message, never the secrets
                st.error(f"Could not read the sheet or the database ({type(ex).__name__}). Check the secrets and the access.")
                df = vol = None
            if vol is not None and vol.empty:
                st.info("No orders were packed in these dates.")
            elif vol is not None:
                act = A.active(df)
                tp, ta = A.person_table(act, vol, "packer", s, e), A.person_table(act, vol, "assembler", s, e)
                inx = act[(act["day"] >= s) & (act["day"] <= e)]
                st.markdown(f"**Showing orders packed {s:%d %b %Y} to {e:%d %b %Y}**")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Packer error %", f"{A.team_error_pct(tp):.2f}")
                m2.metric("Assembler error %", f"{A.team_error_pct(ta):.2f}")
                m3.metric("Internal entries", int((inx["category"] == "Internal").sum()))
                m4.metric("Unknown (no penalty)", int((inx["category"] == "Unknown").sum()))
                lab = RULES["Internal"]["Wrong label / wrong order labelled"]["p"]
                st.caption("Error % = points ÷ orders handled × 100, for orders packed in the chosen dates. "
                           f"A wrong label is {lab:g} points for the packer. Reversed entries, entries with no packer or assembler, "
                           f"and executive / test logins are left out. People with under {C.LOW_VOLUME} orders are marked low volume.")

                show_low = st.checkbox(f"Include low-volume people (under {C.LOW_VOLUME} orders) in the charts", value=False, key="an_low")
                g1, g2 = st.columns(2)
                with g1:
                    accuracy_chart(tp if show_low else tp[tp["note"] == ""], "Packer accuracy %")
                with g2:
                    accuracy_chart(ta if show_low else ta[ta["note"] == ""], "Assembler accuracy %")

                fmt = {"orders": "{:,.0f}", "complaints": "{:.0f}", "points": "{:g}", "error %": "{:.2f}", "accuracy %": "{:.2f}"}
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

# ================================================================= TAB 3: logs - read only, reversal only
with tab_logs:
    if gate("admin_passcode", "Admin passcode", "ok_admin", "in_admin_logs"):
        try:
            df = A.score(sheets.load_errors(), RULES)
        except Exception as ex:
            st.error(f"Could not read the sheet ({type(ex).__name__}). Check the secrets and the access.")
            df = None
        if df is not None:
            loaded = load_range("lg", "Packed in")
            if loaded:
                s, e = loaded
                s1, s2, s3 = st.columns([2, 1, 1])
                q = s1.text_input("Filter the table", placeholder="person, reason, drug code, text…", key="lg_q")
                cat = s2.selectbox("Type", ["All"] + C.CATEGORIES, key="lg_cat")
                show_rev = s3.checkbox("Include reversed", value=True, key="lg_rev")
                d = df[(df["packed_at"].dt.date >= s) & (df["packed_at"].dt.date <= e)]
                if cat != "All": d = d[d["category"] == cat]
                if not show_rev: d = d[d["reversed"] != "Yes"]
                d = A.search(d, q).sort_values("packed_at", ascending=False)
                st.caption(f"{len(d)} entr{'y' if len(d) == 1 else 'ies'} · read-only. To see one in full or reverse it, search its order ID below.")
                view = d.assign(packer=d["packer"].map(A.name_of), assembler=d["assembler"].map(A.name_of))[
                    ["order_id", "packed_at", "category", "reason", "packer", "assembler", "mistakes",
                     "packer_points", "assembler_points", "reversed", "logged_by"]]
                st.dataframe(view, use_container_width=True, hide_index=True)
                st.download_button("Download these rows (CSV)", d.drop(columns=["sheet_row"]).to_csv(index=False).encode(),
                                   "order_errors.csv", "text/csv")

            st.divider()
            st.subheader("Find an order")
            with st.form("lg_find", border=False):
                f1, f2 = st.columns([3, 1], vertical_alignment="bottom")
                typed = f1.text_input("Order ID", placeholder="e.g. 583492", key="lg_oid_in")
                if f2.form_submit_button("Search", use_container_width=True):
                    st.session_state["lg_oid"] = typed.strip()
            oid = st.session_state.get("lg_oid", "")
            if st.session_state.pop("lg_reversed", None):
                st.success("Reversed. The row stays in the log but no longer counts.")
            if oid:
                hits = df[df["order_id"] == oid]
                if hits.empty:
                    st.info(f"No error is logged for order {oid}.")
                for r in hits.itertuples():
                    with st.container(border=True):
                        a, b = st.columns(2)
                        a.markdown(f"**Order** {r.order_id}  \n**Packed** {fd(r.packed_at, '%d %b %Y %H:%M')}  \n"
                                   f"**Packer** {A.name_of(r.packer) or '-'} ({r.packer or '-'})  \n"
                                   f"**Assembler** {A.name_of(r.assembler) or '-'} ({r.assembler or '-'})")
                        b.markdown(f"**Type** {r.category} - {r.reason}  \n**Drugs** {r.drugs_affected or '-'} · **mistakes** {int(r.mistakes)}  \n"
                                   f"**Points** packer {r.packer_points:g}, assembler {r.assembler_points:g}  \n"
                                   f"**Caught by** {r.how_caught}  \n"
                                   f"**Logged by** {r.logged_by} at {r.submitted_at or '-'}")
                        st.markdown(f"**Description:** {r.description}")
                        if r.needs_review:
                            st.warning(f"Import note: {r.needs_review}")
                        if r.reversed == "Yes":
                            st.info(f"Reversed on {r.reversed_on}: {r.reversed_reason}. The entry stays here but its points do not count.")
                        else:
                            with st.form(f"lg_reverse_{r.sheet_row}", clear_on_submit=True):
                                why = st.text_input("Reason for reversing this entry (appeal accepted)")
                                if st.form_submit_button("Reverse this entry"):
                                    if not why.strip():
                                        st.error("Write the reason first.")
                                    else:
                                        try:
                                            sheets.reverse_entry(int(r.sheet_row), why.strip())
                                        except Exception as ex:
                                            st.error(f"Could not reverse ({type(ex).__name__}). Try again.")
                                        else:
                                            st.session_state["lg_reversed"] = True
                                            st.rerun()
