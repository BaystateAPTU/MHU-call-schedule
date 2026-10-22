# Call volunteer & assignment app

Residents volunteer for dates; you rank the volunteers and assign. Built for 6-month blocks.

## Run
```
pip install -r requirements.txt
ADMIN_PASSWORD=choose-one streamlit run app.py
```
Storage
Set DATABASE_URL to a Postgres connection string (Neon or Supabase) and all data lives there. That is required on Streamlit Community Cloud, whose disk is wiped on restart. On Streamlit Cloud put it in App settings > Secrets:
DATABASE_URL = "postgresql://...?sslmode=require"
ADMIN_PASSWORD = "choose-one"
SIGNUP_CODE = "optional-shared-code"   # optional; if set, people need it to create an account
Without DATABASE_URL the app falls back to the local SQLite file below (fine on your own computer) and shows a warning in the sidebar.

Data lives in `call_schedule.db` (SQLite) next to the app. Set `CALL_DB=/path/to.db` to move it.
Back that file up; it is the whole system.

## Workflow
1. **Scheduler > Blocks & holidays**: create the block (end date defaults to 6 months), add holidays (a single date or a From–To range, e.g. "Winter break" 12/24–1/1). Holidays are flagged 🎉 on every calendar view and the Excel export, but are scheduled and counted as the normal weekday/weekend shift they fall on.
2. **People**: residents create their own account on **Volunteer > Create an account** (name + their own PIN, plus the sign-up code if `SIGNUP_CODE` is set) and can change their PIN after signing in. You can still add people and reset PINs under **Scheduler > People**, untick *Active* to hide duplicates, and enter *carryover* shifts already worked this year.
3. Residents open **Volunteer**, sign in, mark each date **Preferred** or **Willing** (blank = can't), Save.
4. **Scheduler > Assign**: pick a ranking mode, then either **Auto-fill empty dates** or assign by hand. Each row lists volunteers in ranked order (`*` = preferred). Save.
5. **Summary**: per-person volunteered / assigned / lifetime totals by weekday and weekend (plus how many were holidays, for info). CSV export of totals and schedule.
6. Set the block to **locked** to stop further volunteering.

## Ranking
Preferred always outranks Willing. Then:
- **Most pick-up first**: people who volunteered for the most dates in the block, then fewest lifetime shifts of that type.
- **Balance first**: fewest lifetime shifts of that type, then fewest this block.

Auto-fill works hardest dates first (fewest volunteers), never overwrites an existing assignment, honors an optional per-person cap, and softly avoids back-to-back days within the same preference level.

## Assumptions to check
- One person covers each date (no primary/backup slots).
- Weekend = Sat/Sun; holidays are whatever you list.
- PINs and the admin password are light access control for an internal tool, not strong security. Run it on an internal network or behind your usual login.
