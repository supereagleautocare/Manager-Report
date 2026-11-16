"""Read Paul's saved daily actuals and shop calendar for the manager feed.

This does not change the PNL scoreboard's payroll costing or saved goals.
"""
import datetime as dt
import math


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def daily_summary(grid, as_of, monday, week_grids=()):
    rows = grid.values
    normalize = lambda value: ' '.join(str(value).lower().split())
    header = next((r for r in rows[:8] if any(normalize(v) == 'gross profit' for v in r)), None)
    if header is None:
        raise ValueError('Daily Business Analysis has no Gross Profit column')
    columns = {normalize(value): i for i, value in enumerate(header) if value is not None}
    required = ['gross profit', 'net sales', 'receipts', 'hours billed', 'sales projections']
    if any(name not in columns for name in required):
        raise ValueError('Daily Business Analysis is missing a required manager-report column')
    value = lambda row, name: number(row[columns[name]]) if columns[name] < len(row) else None
    dated = {}
    for row in rows:
        if len(row) < 4:
            continue
        try:
            day = dt.date.fromisoformat(str(row[2])[:10])
        except ValueError:
            continue
        if day.year != as_of.year or day.month != as_of.month:
            continue
        if day in dated:
            raise ValueError('Daily Business Analysis has duplicate daily rows')
        dated[day] = row
    # A positive daily allocation is Paul's working-day schedule. Holiday rows
    # have no allocation and zero sales projection. Actual receipts keep a
    # genuine zero-allocation trading day open. Never infer closures from sales alone.
    opened = {day for day, row in dated.items()
              if (number(row[0]) or 0) > 0 or (value(row, 'sales projections') or 0) > 0
              or (value(row, 'receipts') or 0) >= .01}
    if not opened:
        raise ValueError('Daily Business Analysis has no working-day schedule')
    week_schedule = {day: day in opened for day in dated}
    for other in week_grids:
        for row in other.values:
            if len(row) < 4:
                continue
            try:
                day = dt.date.fromisoformat(str(row[2])[:10])
            except ValueError:
                continue
            if monday <= day <= monday + dt.timedelta(days=6) and day not in week_schedule:
                week_schedule[day] = ((number(row[0]) or 0) > 0
                                      or (value(row, 'sales projections') or 0) > 0
                                      or (value(row, 'receipts') or 0) >= .01)
    week_dates = [monday + dt.timedelta(days=i) for i in range(7)]
    # At a year boundary the preceding year's workbook may be absent. Preserve
    # PNL's weekday fallback only for dates whose schedule is actually missing.
    week_open = {day for day in week_dates if week_schedule.get(day, day.weekday() < 5)}
    # Paul's E/AA/AD formulas explicitly branch on receipts M < .01: such a row
    # is forecast, not actual. Exclude it even when its date has arrived.
    actual = {day: row for day, row in dated.items()
              if day <= as_of and (value(row, 'receipts') or 0) >= .01}
    missing = sorted(day for day in opened if day <= as_of and day not in actual)
    def total(name, selected):
        values = [value(row, name) for row in selected.values()]
        return sum(values) if all(v is not None for v in values) else None
    week = {day: row for day, row in actual.items() if day >= monday}
    week_elapsed = sum(day <= as_of for day in week_open)
    month_elapsed = sum(day <= as_of for day in opened)
    gp_mtd = total('gross profit', actual) if actual else None
    gp_week = total('gross profit', week) if week else None
    hours = total('hours billed', actual)
    margins = {}
    for name in columns:
        if name.endswith(' margin') and name != 'parts margin':
            margins[name.removesuffix(' margin')] = total(name, week) if week else None
    return dict(week_elapsed=week_elapsed,
                week_total=len(week_open),
                month_elapsed=month_elapsed, month_total=len(opened),
                gp_mtd=gp_mtd, gp_week=gp_week,
                gp_month_pace=gp_mtd / month_elapsed * len(opened) if gp_mtd is not None and month_elapsed else None,
                gp_per_hour=gp_mtd / hours if gp_mtd is not None and hours else None,
                advisor_margins=margins, actual_through=max(actual).isoformat() if actual else None,
                missing_actual_dates=[str(day) for day in missing],
                closed_dates=[str(day) for day in sorted(dated) if day.weekday() < 5 and day not in opened])
