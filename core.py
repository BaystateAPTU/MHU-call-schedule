"""Core logic for the call volunteer / assignment app (no Streamlit imports)."""
from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

import pandas as pd

DB_PATH = os.environ.get("CALL_DB", "call_schedule.db")
LEVELS = ("Preferred", "Willing")
TYPES = ("weekday", "weekend", "holiday")

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    pin_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    carry_weekday INTEGER NOT NULL DEFAULT 0,
    carry_weekend INTEGER NOT NULL DEFAULT 0,
    carry_holiday INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'      -- open | locked
);
CREATE TABLE IF NOT EXISTS holidays (
    date TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS availability (
    block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    level TEXT NOT NULL,                      -- Preferred | Willing
    PRIMARY KEY (block_id, person_id, date)
);
CREATE TABLE IF NOT EXISTS assignments (
    block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    PRIMARY KEY (block_id, date)
);
"""


# ----------------------------------------------------------------- database
@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA)


def query(sql: str, params: tuple = ()) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def execute(sql: str, params: tuple = ()) -> None:
    with conn() as c:
        c.execute(sql, params)


# ------------------------------------------------------------------- people
def hash_pin(pin: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), b"call-volunteer-v1", 50_000).hex()


def add_person(name: str, pin: str) -> None:
    execute("INSERT INTO people (name, pin_hash) VALUES (?, ?)", (name.strip(), hash_pin(pin)))


def set_pin(person_id: int, pin: str) -> None:
    execute("UPDATE people SET pin_hash=? WHERE id=?", (hash_pin(pin), person_id))


def check_pin(person_id: int, pin: str) -> bool:
    rows = query("SELECT pin_hash FROM people WHERE id=?", (person_id,))
    return bool(rows) and rows[0]["pin_hash"] == hash_pin(pin)


def get_people(active_only: bool = True) -> list[dict]:
    sql = "SELECT * FROM people" + (" WHERE active=1" if active_only else "") + " ORDER BY name"
    return query(sql)


# ------------------------------------------------------------------- blocks
def create_block(name: str, start: date, end: date) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO blocks (name, start_date, end_date) VALUES (?,?,?)",
            (name, start.isoformat(), end.isoformat()),
        )
        return cur.lastrowid


def get_blocks(status: str | None = None) -> list[dict]:
    if status:
        return query("SELECT * FROM blocks WHERE status=? ORDER BY start_date DESC", (status,))
    return query("SELECT * FROM blocks ORDER BY start_date DESC")


def block_dates(block: dict) -> list[date]:
    d, end = date.fromisoformat(block["start_date"]), date.fromisoformat(block["end_date"])
    out = []
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out


def six_month_end(start: date) -> date:
    return (pd.Timestamp(start) + pd.DateOffset(months=6) - pd.Timedelta(days=1)).date()


# ----------------------------------------------------------------- holidays
def get_holidays() -> dict[str, str]:
    return {r["date"]: r["name"] for r in query("SELECT date, name FROM holidays")}


def replace_holidays(rows: list[tuple[str, str]]) -> None:
    with conn() as c:
        c.execute("DELETE FROM holidays")
        c.executemany("INSERT OR REPLACE INTO holidays (date, name) VALUES (?,?)", rows)


def day_type(d: date, holidays: dict[str, str] | set[str]) -> str:
    if d.isoformat() in holidays:
        return "holiday"
    return "weekend" if d.weekday() >= 5 else "weekday"


# ------------------------------------------------------------- availability
def get_person_avail(block_id: int, person_id: int) -> dict[str, str]:
    rows = query(
        "SELECT date, level FROM availability WHERE block_id=? AND person_id=?",
        (block_id, person_id),
    )
    return {r["date"]: r["level"] for r in rows}


def save_person_avail(block_id: int, person_id: int, avail: dict[str, str]) -> None:
    with conn() as c:
        c.execute(
            "DELETE FROM availability WHERE block_id=? AND person_id=?", (block_id, person_id)
        )
        c.executemany(
            "INSERT INTO availability (block_id, person_id, date, level) VALUES (?,?,?,?)",
            [(block_id, person_id, d, lvl) for d, lvl in avail.items() if lvl in LEVELS],
        )


def get_block_avail(block_id: int) -> dict[str, dict[int, str]]:
    """date -> {person_id: level}, active people only."""
    out: dict[str, dict[int, str]] = {}
    rows = query(
        """SELECT a.date, a.person_id, a.level FROM availability a
           JOIN people p ON p.id = a.person_id
           WHERE a.block_id=? AND p.active=1""",
        (block_id,),
    )
    for r in rows:
        out.setdefault(r["date"], {})[r["person_id"]] = r["level"]
    return out


# -------------------------------------------------------------- assignments
def get_assignments(block_id: int) -> dict[str, int]:
    rows = query("SELECT date, person_id FROM assignments WHERE block_id=?", (block_id,))
    return {r["date"]: r["person_id"] for r in rows}


def save_assignments(block_id: int, assigned: dict[str, int | None]) -> None:
    with conn() as c:
        c.execute("DELETE FROM assignments WHERE block_id=?", (block_id,))
        c.executemany(
            "INSERT INTO assignments (block_id, date, person_id) VALUES (?,?,?)",
            [(block_id, d, pid) for d, pid in assigned.items() if pid],
        )


# -------------------------------------------------------------------- stats
def person_stats(block_id: int) -> dict[int, dict]:
    """Per active person: volunteer counts for this block, plus assigned shift
    counts by type for this block and lifetime (carryover + all blocks)."""
    hol = get_holidays()
    stats: dict[int, dict] = {}
    for p in get_people():
        stats[p["id"]] = {
            "name": p["name"],
            "pref": 0,
            "will": 0,
            "vol": 0,
            "life": {
                "weekday": p["carry_weekday"],
                "weekend": p["carry_weekend"],
                "holiday": p["carry_holiday"],
            },
            "block": {"weekday": 0, "weekend": 0, "holiday": 0},
            "carry": {
                "weekday": p["carry_weekday"],
                "weekend": p["carry_weekend"],
                "holiday": p["carry_holiday"],
            },
        }
    for r in query("SELECT person_id, level FROM availability WHERE block_id=?", (block_id,)):
        s = stats.get(r["person_id"])
        if not s:
            continue
        s["vol"] += 1
        s["pref" if r["level"] == "Preferred" else "will"] += 1
    for r in query("SELECT block_id, date, person_id FROM assignments"):
        s = stats.get(r["person_id"])
        if not s:
            continue
        t = day_type(date.fromisoformat(r["date"]), hol)
        s["life"][t] += 1
        if r["block_id"] == block_id:
            s["block"][t] += 1
    return stats


# ------------------------------------------------------ ranking / autofill
MODES = {
    "pickup": "Most pick-up first (volunteers for the most dates)",
    "balance": "Balance first (fewest lifetime shifts of that type)",
}


def rank_candidates(
    d: date, avail_d: dict[int, str], stats: dict[int, dict], mode: str, hol: dict[str, str]
) -> list[int]:
    """Order the people who volunteered for date d, best first.
    Preferred always outranks Willing; then the chosen mode; then name."""
    t = day_type(d, hol)

    def key(pid: int):
        lvl = 0 if avail_d[pid] == "Preferred" else 1
        s = stats[pid]
        if mode == "pickup":
            return (lvl, -s["vol"], s["life"][t], s["name"])
        return (lvl, s["life"][t], sum(s["block"].values()), s["name"])

    return sorted((p for p in avail_d if p in stats), key=key)


def autofill(
    block_id: int, mode: str = "pickup", max_per_person: int = 0, avoid_consecutive: bool = True
) -> int:
    """Fill dates that have no assignment yet. Hardest dates (fewest volunteers)
    first. Never overrides an existing assignment. Returns number filled."""
    block = query("SELECT * FROM blocks WHERE id=?", (block_id,))[0]
    hol = get_holidays()
    avail = get_block_avail(block_id)
    assigned: dict[str, int | None] = dict(get_assignments(block_id))
    stats = person_stats(block_id)

    todo = [d for d in block_dates(block) if d.isoformat() in avail and d.isoformat() not in assigned]
    todo.sort(key=lambda d: (len(avail[d.isoformat()]), d))

    filled = 0
    for d in todo:
        iso = d.isoformat()
        ranked = rank_candidates(d, avail[iso], stats, mode, hol)
        if max_per_person:
            ranked = [p for p in ranked if sum(stats[p]["block"].values()) < max_per_person]
        if avoid_consecutive and ranked:
            # Soft rule: within the same preference level, favor people who aren't
            # already covering the day before/after. Never overrides Preferred vs Willing.
            near = {assigned.get((d - timedelta(days=1)).isoformat()), assigned.get((d + timedelta(days=1)).isoformat())}
            ranked = sorted(
                ranked,
                key=lambda p: (0 if avail[iso][p] == "Preferred" else 1, p in near, ranked.index(p)),
            )
        if not ranked:
            continue
        pick = ranked[0]
        assigned[iso] = pick
        t = day_type(d, hol)
        stats[pick]["block"][t] += 1
        stats[pick]["life"][t] += 1
        filled += 1
    save_assignments(block_id, assigned)
    return filled


# ------------------------------------------------------------------ summary
def summary_df(block_id: int) -> pd.DataFrame:
    stats = person_stats(block_id)
    rows = []
    for s in stats.values():
        b, life = s["block"], s["life"]
        n_assigned = sum(b.values())
        rows.append(
            {
                "Person": s["name"],
                "Preferred": s["pref"],
                "Willing": s["will"],
                "Volunteered": s["vol"],
                "Assigned (block)": n_assigned,
                "Weekday": b["weekday"],
                "Weekend": b["weekend"],
                "Holiday": b["holiday"],
                "Lifetime weekday": life["weekday"],
                "Lifetime weekend": life["weekend"],
                "Lifetime holiday": life["holiday"],
                "Lifetime total": sum(life.values()),
            }
        )
    df = pd.DataFrame(rows)
    return df.sort_values(["Volunteered", "Person"], ascending=[False, True]).reset_index(drop=True) if len(df) else df
