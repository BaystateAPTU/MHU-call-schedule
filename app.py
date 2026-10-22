"""Call volunteer + assignment app.

Run:  ADMIN_PASSWORD=yourpassword streamlit run app.py
"""
from __future__ import annotations

import os
from datetime import date

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Call Coverage", page_icon="📞", layout="wide")

# Make Streamlit secrets (e.g. DATABASE_URL) visible to core.py before it connects.
try:
    for _k in ("DATABASE_URL", "ADMIN_PASSWORD"):
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
except Exception:
    pass

import core  # noqa: E402


@st.cache_resource
def _init_db() -> bool:
    core.init_db()
    return True


_init_db()

NONE = "—"


def admin_password() -> str:
    try:
        pw = st.secrets.get("ADMIN_PASSWORD")
    except Exception:
        pw = None
    return pw or os.environ.get("ADMIN_PASSWORD", "")


# ===================================================================== resident
def resident_page() -> None:
    st.header("Volunteer for call")

    people = core.get_people()
    if not people:
        st.info("No people have been added yet. Ask the scheduler to add you.")
        return

    if "resident_id" not in st.session_state:
        with st.form("login"):
            name = st.selectbox("Your name", [p["name"] for p in people])
            pin = st.text_input("PIN", type="password")
            if st.form_submit_button("Sign in"):
                pid = next(p["id"] for p in people if p["name"] == name)
                if core.check_pin(pid, pin):
                    st.session_state["resident_id"] = pid
                    st.session_state["resident_name"] = name
                    st.rerun()
                else:
                    st.error("Name or PIN didn't match.")
        return

    pid, name = st.session_state["resident_id"], st.session_state["resident_name"]
    c1, c2 = st.columns([4, 1])
    c1.write(f"Signed in as **{name}**")
    if c2.button("Sign out"):
        for k in ("resident_id", "resident_name"):
            st.session_state.pop(k, None)
        st.rerun()

    blocks = core.get_blocks("open")
    if not blocks:
        st.info("No block is open for volunteering right now.")
        return
    block = st.selectbox(
        "Block", blocks, format_func=lambda b: f"{b['name']} ({b['start_date']} to {b['end_date']})"
    )

    st.caption(
        "Mark **Preferred** for dates you actively want, **Willing** for dates you'd cover if needed, "
        "and leave blank if you can't. Nothing is final until the scheduler assigns."
    )
    view = st.radio("Show", ["All", "Weekends", "Weekdays", "Holidays"], horizontal=True)

    hol = core.get_holidays()
    mine = core.get_person_avail(block["id"], pid)
    rows = []
    for d in core.block_dates(block):
        t = core.day_type(d, hol)
        if view == "Weekends" and t != "weekend":
            continue
        if view == "Weekdays" and t != "weekday":
            continue
        if view == "Holidays" and t != "holiday":
            continue
        rows.append(
            {
                "Date": d.isoformat(),
                "Day": d.strftime("%a"),
                "Type": t + (f" ({hol[d.isoformat()]})" if d.isoformat() in hol and hol[d.isoformat()] else ""),
                "Availability": mine.get(d.isoformat(), NONE),
            }
        )
    df = pd.DataFrame(rows)
    edited = st.data_editor(
        df,
        key=f"avail_{block['id']}_{view}",
        hide_index=True,
        width="stretch",
        height=560,
        disabled=["Date", "Day", "Type"],
        column_config={
            "Availability": st.column_config.SelectboxColumn(
                options=[NONE, "Preferred", "Willing"], required=True
            )
        },
    )

    if st.button("Save my availability", type="primary"):
        merged = dict(mine)
        for _, r in edited.iterrows():
            if r["Availability"] in core.LEVELS:
                merged[r["Date"]] = r["Availability"]
            else:
                merged.pop(r["Date"], None)
        core.save_person_avail(block["id"], pid, merged)
        n_pref = sum(1 for v in merged.values() if v == "Preferred")
        n_will = sum(1 for v in merged.values() if v == "Willing")
        st.success(f"Saved: {n_pref} preferred, {n_will} willing.")


# ======================================================================== admin
def admin_login() -> bool:
    if st.session_state.get("is_admin"):
        return True
    pw = admin_password()
    if not pw:
        st.error("No admin password is set. Start the app with ADMIN_PASSWORD=... (or add it to .streamlit/secrets.toml).")
        return False
    with st.form("admin_login"):
        entered = st.text_input("Admin password", type="password")
        if st.form_submit_button("Sign in"):
            if entered == pw:
                st.session_state["is_admin"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    return False


def tab_blocks() -> None:
    st.subheader("Blocks")
    with st.form("new_block"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Block name", placeholder="Jan–Jun 2027")
        start = c2.date_input("Start", value=date.today())
        end = c3.date_input("End (default: 6 months)", value=core.six_month_end(date.today()))
        if st.form_submit_button("Create block"):
            if not name.strip():
                st.error("Give the block a name.")
            elif end < start:
                st.error("End date is before start date.")
            else:
                core.create_block(name.strip(), start, end)
                st.success("Block created (open for volunteering).")
                st.rerun()

    for b in core.get_blocks():
        c1, c2, c3 = st.columns([4, 2, 2])
        c1.write(f"**{b['name']}**  \n{b['start_date']} to {b['end_date']}")
        status = c2.radio(
            "Status", ["open", "locked"], index=0 if b["status"] == "open" else 1,
            key=f"status_{b['id']}", horizontal=True, label_visibility="collapsed",
        )
        if status != b["status"]:
            core.execute("UPDATE blocks SET status=? WHERE id=?", (status, b["id"]))
            st.rerun()
        if c3.checkbox("Confirm delete", key=f"delchk_{b['id']}") and c3.button("Delete", key=f"del_{b['id']}"):
            core.execute("DELETE FROM blocks WHERE id=?", (b["id"],))
            st.rerun()

    st.subheader("Holidays")
    st.caption("Dates listed here count as holiday coverage instead of weekday/weekend.")
    hol = core.get_holidays()
    hdf = pd.DataFrame(
        {"Date": [date.fromisoformat(d) for d in sorted(hol)], "Name": [hol[d] for d in sorted(hol)]}
    )
    if hdf.empty:
        hdf = pd.DataFrame({"Date": pd.Series(dtype="object"), "Name": pd.Series(dtype="str")})
    edited = st.data_editor(
        hdf, num_rows="dynamic", hide_index=True, key="holidays_editor",
        column_config={"Date": st.column_config.DateColumn(required=True), "Name": st.column_config.TextColumn()},
    )
    if st.button("Save holidays"):
        rows = [
            (pd.Timestamp(r["Date"]).date().isoformat(), str(r["Name"] or ""))
            for _, r in edited.iterrows()
            if pd.notna(r["Date"])
        ]
        core.replace_holidays(rows)
        st.success("Holidays saved.")
        st.rerun()


def tab_people() -> None:
    st.subheader("People")
    with st.form("new_person", clear_on_submit=True):
        c1, c2 = st.columns(2)
        name = c1.text_input("Name")
        pin = c2.text_input("PIN (they use this to sign in)")
        if st.form_submit_button("Add person"):
            if not name.strip() or not pin.strip():
                st.error("Name and PIN are both required.")
            else:
                try:
                    core.add_person(name, pin)
                    st.success(f"Added {name.strip()}.")
                    st.rerun()
                except Exception:
                    st.error("That name already exists.")

    people = core.get_people(active_only=False)
    if not people:
        return
    st.caption(
        "Carryover = shifts already worked before this app started tracking, so the lifetime totals "
        "reflect the whole year."
    )
    df = pd.DataFrame(
        [
            {
                "id": p["id"], "Name": p["name"], "Active": bool(p["active"]),
                "Carry weekday": p["carry_weekday"], "Carry weekend": p["carry_weekend"],
                "Carry holiday": p["carry_holiday"],
            }
            for p in people
        ]
    )
    edited = st.data_editor(
        df, hide_index=True, disabled=["id", "Name"], key="people_editor",
        column_config={
            "id": None,
            "Carry weekday": st.column_config.NumberColumn(min_value=0, step=1),
            "Carry weekend": st.column_config.NumberColumn(min_value=0, step=1),
            "Carry holiday": st.column_config.NumberColumn(min_value=0, step=1),
        },
    )
    if st.button("Save people"):
        for _, r in edited.iterrows():
            core.execute(
                "UPDATE people SET active=?, carry_weekday=?, carry_weekend=?, carry_holiday=? WHERE id=?",
                (int(r["Active"]), int(r["Carry weekday"]), int(r["Carry weekend"]),
                 int(r["Carry holiday"]), int(r["id"])),
            )
        st.success("Saved.")
        st.rerun()

    with st.expander("Reset a PIN"):
        who = st.selectbox("Person", people, format_func=lambda p: p["name"], key="pin_who")
        new_pin = st.text_input("New PIN", key="pin_new")
        if st.button("Set PIN") and new_pin.strip():
            core.set_pin(who["id"], new_pin.strip())
            st.success("PIN updated.")


def tab_assign() -> None:
    st.subheader("Assign coverage")
    blocks = core.get_blocks()
    if not blocks:
        st.info("Create a block first.")
        return
    block = st.selectbox(
        "Block", blocks, key="assign_block",
        format_func=lambda b: f"{b['name']} ({b['start_date']} to {b['end_date']}) [{b['status']}]",
    )
    bid = block["id"]

    c1, c2, c3 = st.columns([3, 1, 2])
    mode = c1.selectbox("Rank volunteers by", list(core.MODES), format_func=core.MODES.get)
    cap = c2.number_input("Max shifts / person", min_value=0, value=0, help="0 = no cap")
    avoid = c3.checkbox("Avoid back-to-back days when possible", value=True)

    b1, b2, _ = st.columns([1, 1, 4])
    if b1.button("Auto-fill empty dates"):
        n = core.autofill(bid, mode, int(cap), avoid)
        st.toast(f"Filled {n} dates. Review and adjust below.")
        st.rerun()
    if b2.button("Clear all"):
        core.save_assignments(bid, {})
        st.rerun()

    hol = core.get_holidays()
    avail = core.get_block_avail(bid)
    stats = core.person_stats(bid)
    assigned = core.get_assignments(bid)
    names = {pid: s["name"] for pid, s in stats.items()}
    id_by_name = {v: k for k, v in names.items()}

    rows = []
    gaps = []
    for d in core.block_dates(block):
        iso = d.isoformat()
        cand = core.rank_candidates(d, avail.get(iso, {}), stats, mode, hol)
        ranked = ", ".join(
            f"{names[p]}{'*' if avail[iso][p] == 'Preferred' else ''}" for p in cand
        )
        if not cand and iso not in assigned:
            gaps.append(iso)
        rows.append(
            {
                "Date": iso,
                "Day": d.strftime("%a"),
                "Type": core.day_type(d, hol),
                "# Vol": len(cand),
                "Volunteers (ranked, * = preferred)": ranked,
                "Assigned": names.get(assigned.get(iso), NONE) if assigned.get(iso) in names else NONE,
            }
        )
    df = pd.DataFrame(rows)

    show = st.radio("Show", ["All", "Unassigned", "Weekends", "Weekdays", "Holidays"], horizontal=True, key="assign_view")
    mask = pd.Series(True, index=df.index)
    if show == "Unassigned":
        mask = df["Assigned"] == NONE
    elif show in ("Weekends", "Weekdays", "Holidays"):
        mask = df["Type"] == {"Weekends": "weekend", "Weekdays": "weekday", "Holidays": "holiday"}[show]

    if gaps:
        st.warning(f"{len(gaps)} dates have no volunteers and no assignment yet.")

    edited = st.data_editor(
        df[mask],
        key=f"assign_{bid}_{show}_{mode}",
        hide_index=True,
        width="stretch",
        height=620,
        disabled=["Date", "Day", "Type", "# Vol", "Volunteers (ranked, * = preferred)"],
        column_config={
            "Assigned": st.column_config.SelectboxColumn(options=[NONE] + sorted(id_by_name), required=True),
            "# Vol": st.column_config.NumberColumn(width="small"),
        },
    )
    allow_nonvol = st.checkbox("Allow assigning someone who didn't volunteer for that date")

    if st.button("Save assignments", type="primary"):
        new = dict(assigned)
        offenders = []
        for _, r in edited.iterrows():
            iso, who = r["Date"], r["Assigned"]
            if who == NONE:
                new.pop(iso, None)
                continue
            pid = id_by_name[who]
            if pid not in avail.get(iso, {}):
                offenders.append(f"{who} on {iso}")
            new[iso] = pid
        if offenders and not allow_nonvol:
            st.error("Not saved — these people didn't volunteer: " + "; ".join(offenders)
                     + ". Tick the override box above if that's intentional.")
        else:
            core.save_assignments(bid, new)
            st.success("Assignments saved.")
            st.rerun()


def tab_summary() -> None:
    st.subheader("Summary")
    blocks = core.get_blocks()
    if not blocks:
        st.info("Create a block first.")
        return
    block = st.selectbox(
        "Block", blocks, key="summary_block",
        format_func=lambda b: f"{b['name']} ({b['start_date']} to {b['end_date']})",
    )
    df = core.summary_df(block["id"])
    st.dataframe(df, hide_index=True, width="stretch")
    st.download_button("Download summary CSV", df.to_csv(index=False), file_name="call_summary.csv")

    out = core.schedule_df(block["id"])
    c1, c2, _ = st.columns([1, 1, 3])
    c1.download_button(
        "Download schedule (Excel)",
        core.schedule_xlsx(block["id"]),
        file_name=f"call_schedule_{block['name'].replace(' ', '_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
    c2.download_button("Download schedule CSV", out.to_csv(index=False), file_name="call_schedule.csv")


def admin_page() -> None:
    st.header("Scheduler")
    if not admin_login():
        return
    if st.button("Sign out of admin"):
        st.session_state.pop("is_admin", None)
        st.rerun()
    t1, t2, t3, t4 = st.tabs(["Assign", "Summary", "Blocks & holidays", "People"])
    with t1:
        tab_assign()
    with t2:
        tab_summary()
    with t3:
        tab_blocks()
    with t4:
        tab_people()


# ======================================================================== main
page = st.sidebar.radio("Go to", ["Volunteer", "Scheduler"])
if not core.using_postgres():
    st.sidebar.caption("⚠️ Storage: local SQLite file. Data will be lost on Streamlit Cloud restarts. Set DATABASE_URL.")
if page == "Volunteer":
    resident_page()
else:
    admin_page()
