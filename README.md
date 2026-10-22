# Call volunteer & assignment app

Residents volunteer for dates; you rank the volunteers and assign. Built for 6-month blocks.

## Run
```
pip install -r requirements.txt
ADMIN_PASSWORD=choose-one streamlit run app.py
```
Data lives in `call_schedule.db` (SQLite) next to the app. Set `CALL_DB=/path/to.db` to move it.
Back that file up; it is the whole system.

## Workflow
1. **Scheduler > Blocks & holidays**: create the block (end date defaults to 6 months), add holidays.
2. **Scheduler > People**: add everyone with a PIN. Enter *carryover* shifts already worked this year so lifetime totals are right from day one.
3. Residents open **Volunteer**, sign in, mark each date **Preferred** or **Willing** (blank = can't), Save.
4. **Scheduler > Assign**: pick a ranking mode, then either **Auto-fill empty dates** or assign by hand. Each row lists volunteers in ranked order (`*` = preferred). Save.
5. **Summary**: per-person volunteered / assigned / lifetime totals by weekday, weekend, holiday. CSV export of totals and schedule.
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
