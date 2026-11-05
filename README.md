# Red Star dashboard refresh

Public code for the scheduled task **"Red Star dashboard sheets daily refresh"** (9:10 AM and 2:10 PM Arizona).
It replaces the old builder that was stored inside the dashboard: code downloaded from the dashboard is now
treated as untrusted, so unattended runs refused to execute it (Nov 4–5, 2026).

## What it builds
- Google Sheets copies: Discord Tracking (7 tabs) and Lapsed Customers Text Data (Campaigns, Reply flags) every run;
  Competitor Tracking (6 tabs) on the 2nd and 6th of Jan, Feb, Apr, May, Jul, Aug, Oct and Nov (morning run).
- `daily_sales`: last 42 days per store with the same weekday last year (morning run, two Square loads).
- `discord_home`: the home screen's Discord line (latest company update, who still has to react) — `discord_home.py`.
- `home_pack`: the home summary (alerts and "What to do" notes) — `home_pack.py`; rebuilt only when one of its
  20 Square files changed (normally after the Monday refreshes). `--force-pack` rebuilds it anyway.
- `data_updated`: when each data source last changed (the dashboard's "Updated" line).
- Watchdog: reports other datasets whose weekly/monthly refresh was missed (`OVERDUE ...`).

Both were checked against the dashboard's own files on Nov 5, 2026: identical output (19 and 1,179 rows).

## How the task uses it
1. The task makes the tool calls (Sheets `get_values`, Square reporting loads, ArtifactData reads), runs
   `python3 refresh.py plan <work>` and downloads the files it lists into `<work>/blobs/`.
2. `python3 refresh.py build <work> [--afternoon]` reads those answers from the session log and writes `<work>/out/*.json`.
3. The task uploads the listed files, then runs `python3 refresh.py finish <work> dataset=/_blob/<id> ...`
   and applies the printed ArtifactData batch, then deletes the printed old file ids.

Read-only on Google Sheets and Square. Never reads the RSV Employees Contact List.
