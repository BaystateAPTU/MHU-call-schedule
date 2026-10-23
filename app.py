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
    for _k in ("DATABASE_URL", "ADMIN_PASSWORD", "SIGNUP_CODE"):
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
MIN_PIN = 4


def signup_code() -> str:
    """Optional shared code people must enter to create an account (blank = open sign-up)."""
    try:
        code = st.secrets.get("SIGNUP_CODE")
    except Exception:
        code = None
    return str(code or os.environ.get("SIGNUP_CODE", "")).strip()


def pin_problem(pin: str, confirm: str) -> str | None:
    if len(pin) < MIN_PIN:
        return f"PIN must be at least {MIN_PIN} characters."
    if pin != confirm:
        return "PINs don't match."
    return None


def sign_in(pid: int, name: str) -> None:
    st.session_state["resident_id"] = pid
    st.session_state["resident_name"] = name
    st.rerun()


def resident_auth() -> None:
    people = core.get_people()
    t_in, t_new = st.tabs(["Sign in", "New here? Create an account"])

    with t_in:
        if not people:
            st.info("Nobody has signed up yet — use **Create an account**.")
        else:
            with st.form("login"):
                name = st.selectbox("Your name", [p["name"] for p in people])
                pin = st.text_input("PIN", type="password")
                if st.form_submit_button("Sign in", type="primary"):
                    pid = next(p["id"] for p in people if p["name"] == name)
                    if core.check_pin(pid, pin):
                        sign_in(pid, name)
                    else:
                        st.error("Name or PIN didn't match. Forgot it? Ask the scheduler to reset it.")

    with t_new:
        code_needed = signup_code()
        with st.form("signup"):
            st.caption("Use the name you want to appear on the schedule (e.g. *Jane Smith*).")
            name = st.text_input("Your name")
            c1, c2 = st.columns(2)
            pin = c1.text_input(f"Choose a PIN (at least {MIN_PIN} characters)", type="password")
            confirm = c2.text_input("Confirm PIN", type="password")
            code = st.text_input("Sign-up code (from the scheduler)", type="password") if code_needed else ""
            if st.form_submit_button("Create account", type="primary"):
                clean = core.clean_name(name)
                problem = pin_problem(pin, confirm)
                if len(clean) < 2:
                    st.error("Enter your name.")
                elif problem:
                    st.error(problem)
                elif code_needed and code.strip() != code_needed:
                    st.error("Sign-up code is incorrect.")
                elif core.name_taken(clean):
                    st.error(f"“{clean}” is already registered. Sign in instead, or ask the scheduler "
                             "to reset your PIN.")
                else:
                    try:
                        pid = core.add_person(clean, pin)
                    except Exception:
                        st.error("Couldn't create that account — the name may already be taken.")
                    else:
                        sign_in(pid, clean)


def admin_password() -> str:
    try:
        pw = st.secrets.get("ADMIN_PASSWORD")
    except Exception:
        pw = None
    return pw or os.environ.get("ADMIN_PASSWORD", "")


# ===================================================================== resident
def resident_page() -> None:
    st.header("Volunteer for call")

    if "resident_id" not in st.session_state:
        resident_auth()
        return

    pid, name = st.session_state["resident_id"], st.session_state["resident_name"]
    c1, c2 = st.columns([4, 1])
    c1.write(f"Signed in as **{name}**")
    if c2.button("Sign out"):
        for k in ("resident_id", "resident_name"):
            st.session_state.pop(k, None)
        st.rerun()

    with st.expander("Change my PIN"):
        with st.form("change_pin", clear_on_submit=True):
            cur = st.text_input("Current PIN", type="password")
            c1, c2 = st.columns(2)
            new = c1.text_input("New PIN", type="password")
            confirm = c2.text_input("Confirm new PIN", type="password")
            if st.form_submit_button("Update PIN"):
                problem = pin_problem(new, confirm)
                if not core.check_pin(pid, cur):
                    st.error("Current PIN is incorrect.")
                elif problem:
                    st.error(problem)
                else:
                    core.set_pin(pid, new)
                    st.success("PIN updated.")

    blocks = core.get_blocks("open")
    if not blocks:
        st.info("No block is open for volunteering right now.")
        return
    block = st.selectbox(
        "Block", blocks, format_func=lambda b: f"{b['name']} ({b['start_date']} to {b['end_date']})"
    )

    mode = st.segmented_control(
        "View", ["📅 Calendar", "📋 List"], default="📅 Calendar", key="vol_view_mode"
    )
    if mode == "📋 List":
        availability_list(block, pid)
    else:
        availability_calendar(block, pid)


CAL_CSS = """
<style>
.st-key-calgrid [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 4px !important; }
.st-key-calgrid [data-testid="stColumn"] { min-width: 0 !important; flex: 1 1 0 !important; width: auto !important; }
.st-key-calgrid .dow { text-align: center; font-size: .75rem; opacity: .7; font-weight: 600; }
[class*="st-key-cell-"], [class*="st-key-cell-"] > div, [class*="st-key-cell-"] [data-testid="stButton"] { width: 100% !important; }
[class*="st-key-cell-"] button {
    width: 100%; min-height: 3.1rem; padding: 2px 0 !important; font-size: .9rem; line-height: 1.1;
}
[class*="st-key-cell-"][class*="-we-"] button { background: rgba(120,140,170,.14); }
[class*="st-key-cell-"][class*="-hol-"] button { border: 2px dashed #e8833a !important; }
[class*="st-key-cell-P-"] button { background: #2e7d32 !important; color: #fff !important; border-color: #2e7d32; }
[class*="st-key-cell-W-"] button { background: #f6c343 !important; color: #222 !important; border-color: #e0ad2a; }
[class*="st-key-cell-"] button:hover { filter: brightness(1.08); }
.cal-legend span { display: inline-block; padding: 1px 8px; border-radius: 6px; margin-right: 6px; font-size: .85rem; }
</style>
"""

BRUSHES = {"🟢 Preferred": "Preferred", "🟡 Willing": "Willing", "⬜ Clear": None}


def availability_calendar(block: dict, pid: int) -> None:
    st.markdown(CAL_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="cal-legend">Pick a marker, then tap days. Tap a day again to clear it. '
        "Changes save automatically.<br>"
        '<span style="background:#2e7d32;color:#fff">Preferred</span> want it'
        '&nbsp;&nbsp;<span style="background:#f6c343;color:#222">Willing</span> will cover if needed'
        '&nbsp;&nbsp;<span style="border:2px dashed #e8833a">🎉 Holiday</span>'
        '&nbsp;&nbsp;<span style="background:rgba(120,140,170,.14)">Weekend</span></div>',
        unsafe_allow_html=True,
    )
    calendar_fragment(block, pid)


@st.fragment
def calendar_fragment(block: dict, pid: int) -> None:
    import calendar as _cal

    bid = block["id"]
    hol = core.get_holidays()
    mine = core.get_person_avail(bid, pid)
    days = core.block_dates(block)
    in_block = {d.isoformat() for d in days}
    months = sorted({(d.year, d.month) for d in days})
    labels = [date(y, m, 1).strftime("%b %Y") for y, m in months]

    c1, c2 = st.columns([3, 2])
    brush_label = c1.segmented_control(
        "Marker", list(BRUSHES), default="🟢 Preferred", key=f"brush_{bid}"
    )
    brush_label = brush_label or "🟢 Preferred"  # tapping the selected marker deselects it
    brush = BRUSHES[brush_label]
    n_pref = sum(v == "Preferred" for v in mine.values())
    n_will = sum(v == "Willing" for v in mine.values())
    c2.markdown(f"**Your picks this block:** {n_pref} preferred · {n_will} willing")

    month_label = st.pills("Month", labels, default=labels[0], key=f"month_{bid}") or labels[0]
    y, m = months[labels.index(month_label)]

    with st.container(key="calgrid"):
        cols = st.columns(7)
        for i, name in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
            cols[i].markdown(f'<div class="dow">{name}</div>', unsafe_allow_html=True)
        for week in _cal.Calendar(firstweekday=6).monthdatescalendar(y, m):
            cols = st.columns(7)
            for i, d in enumerate(week):
                iso = d.isoformat()
                if d.month != m or iso not in in_block:
                    cols[i].write("")
                    continue
                lvl = mine.get(iso)
                h = core.holiday_label(d, hol)
                state = {"Preferred": "P", "Willing": "W"}.get(lvl, "N")
                tags = ("we-" if d.weekday() >= 5 else "") + ("hol-" if h else "")
                with cols[i].container(key=f"cell-{state}-{tags}{iso}"):
                    label = f"{d.day}{' 🎉' if h else ''}"
                    tip = d.strftime("%a %b %-d") + (f" — {h}" if h else "") + (f" — {lvl}" if lvl else "")
                    if st.button(label, key=f"btn_{bid}_{iso}", help=tip, width="stretch"):
                        new = None if lvl == brush else brush
                        core.set_day_avail(bid, pid, iso, new)
                        st.rerun(scope="fragment")

    month_isos = [d.isoformat() for d in days if (d.year, d.month) == (y, m)]
    we = [i for i in month_isos if date.fromisoformat(i).weekday() >= 5]
    wd = [i for i in month_isos if date.fromisoformat(i).weekday() < 5]
    hd = [i for i in month_isos if i in hol]
    what = brush_label.split(" ", 1)[1]
    st.caption(f"Quick fill for {month_label} (uses the {what} marker):")
    b1, b2, b3, b4 = st.columns(4)
    for col, text, isos in (
        (b1, "All weekends", we), (b2, "All weekdays", wd), (b3, "All holidays", hd), (b4, "Whole month", month_isos),
    ):
        if col.button(text, key=f"bulk_{text}_{bid}_{y}{m}", width="stretch", disabled=not isos):
            core.set_days_avail(bid, pid, isos, brush)
            st.rerun(scope="fragment")


def availability_list(block: dict, pid: int) -> None:
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
        h = core.holiday_label(d, hol)
        if view == "Weekends" and t != "weekend":
            continue
        if view == "Weekdays" and t != "weekday":
            continue
        if view == "Holidays" and not h:
            continue
        rows.append(
            {
                "Date": d.isoformat(),
                "Day": d.strftime("%a"),
                "Type": t,
                "Holiday": f"🎉 {h}" if h else "",
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
        disabled=["Date", "Day", "Type", "Holiday"],
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
    st.caption("Holidays are flagged on the calendar (🎉) so people can see them. They are scheduled and "
               "counted as the normal weekday or weekend shift they fall on.")
    hol = core.get_holidays()
    with st.form("holiday_range", clear_on_submit=True):
        st.markdown("**Add a holiday or date range**")
        c1, c2, c3 = st.columns([2, 1, 1])
        h_name = c1.text_input("Name", placeholder="Winter break")
        h_start = c2.date_input("From", value=None, format="MM/DD/YYYY")
        h_end = c3.date_input("To (leave blank for one day)", value=None, format="MM/DD/YYYY")
        if st.form_submit_button("Add"):
            h_end = h_end or h_start
            if not h_start:
                st.error("Pick a start date.")
            elif h_end < h_start:
                st.error("End date is before start date.")
            elif (h_end - h_start).days > 60:
                st.error("That range is over 60 days — check the dates.")
            else:
                n = core.add_holiday_range(h_name.strip(), h_start, h_end)
                st.success(f"Added {n} day{'s' if n != 1 else ''}.")
                st.rerun()
    st.caption("All holiday dates (edit names or delete rows here, then Save):")
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
    st.caption("People can sign up themselves on the Volunteer page"
               + (" (with the sign-up code)." if signup_code() else ".")
               + " You can also add someone here, or untick **Active** to hide a duplicate or someone who left.")
    with st.form("new_person", clear_on_submit=True):
        c1, c2 = st.columns(2)
        name = c1.text_input("Name")
        pin = c2.text_input("PIN (they use this to sign in)")
        if st.form_submit_button("Add person"):
            if not name.strip() or not pin.strip():
                st.error("Name and PIN are both required.")
            else:
                if core.name_taken(name):
                    st.error("That name already exists.")
                else:
                    core.add_person(name, pin)
                    st.success(f"Added {core.clean_name(name)}.")
                    st.rerun()

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
        },
    )
    if st.button("Save people"):
        for _, r in edited.iterrows():
            core.execute(
                "UPDATE people SET active=?, carry_weekday=?, carry_weekend=? WHERE id=?",
                (int(r["Active"]), int(r["Carry weekday"]), int(r["Carry weekend"]), int(r["id"])),
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
                "Holiday": f"🎉 {core.holiday_label(d, hol)}" if iso in hol else "",
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
    elif show == "Holidays":
        mask = df["Holiday"] != ""
    elif show in ("Weekends", "Weekdays"):
        mask = df["Type"] == {"Weekends": "weekend", "Weekdays": "weekday"}[show]

    if gaps:
        st.warning(f"{len(gaps)} dates have no volunteers and no assignment yet.")

    edited = st.data_editor(
        df[mask],
        key=f"assign_{bid}_{show}_{mode}",
        hide_index=True,
        width="stretch",
        height=620,
        disabled=["Date", "Day", "Type", "Holiday", "# Vol", "Volunteers (ranked, * = preferred)"],
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
