# Super Eagle manager report

Manager dashboard matching the State of the Union template. It shows technician
hours, advisor/writer GP, shop monthly/weekly/daily GP, and MTD average RO, average
quote, GP per billed hour and cars. It automatically refreshes every
60 seconds while open and includes a print layout.

The GP section shows earned MTD GP once, then a consistent monthly/weekly/daily
pace-versus-goal table. Each row states its working days and above/below-goal
amount. The weekly figure is explicitly derived from the month's daily average;
it is not labeled as this week's actual GP.

## One source for the numbers

The app reads the running **PNL Report** service, rather than duplicating its
database queries or financial formulas. PNL remains the source for working days,
official goals, actuals and monthly tracking. Changes to those values or PNL's
existing calculations appear on refresh. If PNL changes its feed contract, the
feed must retain schema version 1 or the manager app must be updated with it.

The manager feed reads Paul's saved Daily Business Analysis daily GP actuals and
working-day allocations. Pace calendars count weekdays, excluding the shop's
scheduled closures (November 26?27 are closed in the current 2026 workbook).
Weekend actual GP remains in the MTD total but does not add a pace day. Forecast
rows are excluded: Paul's sheet distinguishes them by receipts below $0.01.
Missing actual dates are shown as a warning, never counted as saved sales. The
underlying PNL scoreboard and its payroll-based calculations are unchanged.

Monthly, weekly and daily shop GP pace all use the same MTD daily average:
MTD saved GP / elapsed shop working days, multiplied by the period's working
days. The month-end total in Paul's workbook contains future forecasts and is
not used as MTD actual GP. Advisor GP uses his daily advisor-margin columns for
the selected week's posted sales; the table includes Service Advisors only.
Posted sales, ARO, average quote and technician completed hours use the current
Tekmetric warehouse. GP/hour uses Paul's saved GP / saved billed hours. Car pace
uses posted ROs / elapsed days ? month working days; these are ROs, not unique
vehicles. Staff weekly pace still uses each person's WTD actual.

Chris Rapp is displayed as Vegas, as confirmed by the user. Persistent manager
goals remain keyed to the full employee name. Official goals remain linked to
PNL; the older reference's goals are not substituted. Selecting November 11 shows
a reference comparison, including discrepancies in the reference's printed totals.
Reference values never replace calculated actuals.

Optional manager goals (the **Manager goals** panel at the bottom) let the
manager choose which goals to set: shop goals for the month (monthly GP, average
repair order, average quote, GP per billed hour, cars posted) and full-week
targets for each technician and advisor. Each field shows the P&L goal as a hint.
Monthly GP and cars compare with month pace; the rate metrics compare with the
MTD actual; staff targets compare with week pace. Saving them does
not override PNL's official goals or update the source databases. Targets persist
across dates and devices until changed, in the manager service's own SQLite file.
People and totals reflect the rows PNL currently includes; missing official goals
are shown as unset, never zero. Date selection covers the preceding year.

## Editable working days

Use **Edit working days** next to the day counts. Blank fields follow PNL's
automatic calendar; **Use P&L days** removes the selected period's overrides.
Week totals are saved for their Monday-start week, month totals for their month,
and elapsed-day overrides for the selected report date. These values persist on
the manager volume across devices and deployments. They never edit PNL's source.

Edits recalculate GP pace, staff pace, car-count pace and prorated week/day goals.
Monthly PNL targets and financial actuals stay unchanged. Counts must be whole
numbers within the calendar period, with elapsed days no greater than total days.
If a saved total becomes invalid as days advance, it is not silently clamped:
the report uses PNL defaults and shows a correction notice.

The PNL feed preserves the structured day counts actually printed on its
**Week at a Glance** page. A visible, printable note compares those counts with
the manager report's effective counts, including differences that already exist
between Paul's daily schedule and Week at a Glance. The note disappears when
all four counts agree. Saved overrides still carry an explicit edited-days label.

## Required PNL integration

Railway project: `Tekmetric data base` (`5add58a1-e293-4f7c-ab52-7f98c7e9f647`).

1. Copy `integration/pnl_manager_feed.py` to `report/manager_feed.py` and
   `integration/pnl_manager_daily.py` to `report/manager_daily.py` in
   `supereagleautocare/PNL`.
2. Append these two lines to `report/web.py`:

   ```python
   from .manager_feed import register as register_manager_feed
   register_manager_feed(app, report_for)
   ```

3. Set a new random `MANAGER_REPORT_TOKEN` on **PNL Report**. This grants only
   access to the sanitized manager feed. No existing login credential is reused.
4. Deploy PNL Report with that change. Its new GET
   `/internal/manager-report?as_of=YYYY-MM-DD` requires
   `Authorization: Bearer <token>`. The feed reads through the existing cached
   `report_for` and enforces read-only connections to both PNL and Tekmetric.
   It exposes no payroll, customer information, notes or raw tickets.

The generated `integration/pnl-manager-feed.patch` applies the same source change
to the inspected PNL revision. No production service has been changed by building
this repo.

## Manager-Report Railway service

The existing **Manager-Report** service is already connected to this GitHub repo.
Builds use the included Dockerfile; Railway healthcheck is `/health`.

Set these on Manager-Report:

| Variable | Value |
| --- | --- |
| `PNL_REPORT_URL` | PNL Report's private URL and actual listening port, or `https://pnl-report-production.up.railway.app` |
| `PNL_REPORT_TOKEN` | Reference `${{PNL Report.MANAGER_REPORT_TOKEN}}` |
| `MANAGER_USERNAME` | Manager's chosen login name |
| `MANAGER_PASSWORD` | A strong manager password |
| `MANAGER_SECRET_KEY` | A persistent random secret, e.g. `python -c "import secrets; print(secrets.token_hex(32))"` |
| `MANAGER_GOALS_PATH` | `/data/manager-goals.sqlite3` |

Mount a persistent Railway volume at `/data`. Run one replica (multiple Gunicorn
workers are supported). Back up this volume to preserve personal manager targets.
The manager service needs no accounting or Tekmetric database credentials.
Generate a service domain after deployment. Credentials stay server-side;
authenticated browser requests use HttpOnly session cookies and goal saves require
a CSRF token. An unavailable source produces a visible error; the app never
substitutes demonstration numbers or silently serves stale values.

## Local development

```powershell
python -m pip install -r requirements-dev.txt
# Set the variables above in the process environment. .env.example is a reference;
# the app does not automatically load a .env file.
python -m flask --app manager.app run --port 8081
python -m pytest -q
```

Production numbers require the PNL feed integration and its token. Tests use
synthetic fixtures without accessing Railway or sending email.
