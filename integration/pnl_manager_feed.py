"""Install as report/manager_feed.py in supereagleautocare/PNL.

The feed only reads the existing report. It has no write operations and returns
no raw tickets, customer details, payroll, notes or credentials.
"""
import datetime as dt
import hmac
import os
from zoneinfo import ZoneInfo

from flask import abort, jsonify, request


def project(report, week_total, generated_at, daily=None):
    """Versioned, deliberately narrow contract over the current PNL report."""
    scoreboard = {r['label']: r for r in report['front']['scoreboard']}
    gp = scoreboard['Gross profit']
    kpis = []
    for label, display, kind in [('Average ticket', 'Average repair order', 'money'),
                                  ('Average quote', 'Average quote', 'money'),
                                  ('GP per billed hour', 'GP per billed hour', 'money'),
                                  ('Cars posted', 'Cars posted', 'num')]:
        row = scoreboard[label]
        kpis.append(dict(label=display, kind=kind, actual=row['mtd'], goal=row['mtd_goal'],
                         pace=row.get('tracking') if label == 'Cars posted' else None))
    elapsed = report['days_open']
    result = dict(schema_version=1, as_of=report['end'], generated_at=generated_at,
                freshness=report['freshness'],
                calendar=dict(week_start=report['start'], week_elapsed=elapsed, week_total=week_total,
                              month_start=report['month']['start'], month_end=report['month']['end'],
                              month_elapsed=report['month']['days_worked'], month_total=report['month']['days_open']),
                gp=dict(week=gp['week'], mtd=gp['mtd'], month_goal=gp['mtd_goal'], month_pace=gp['tracking']),
                tracking_from_paul=report['front']['tracking_from_paul'],
                techs=[dict(name=p['name'], actual=p['hours_turned'],
                            goal=p['hours_goal_week'] * week_total / 5)
                       for p in report['techs']['each']],
                advisors=[dict(name=p['name'], role=p['role'], actual=p['gp'], sales=p['net_sales'],
                               goal=p['gp_goal'] / elapsed * week_total
                               if p['gp_goal'] is not None and elapsed else None)
                          for p in report['advisors']['each']], kpis=kpis)
    if daily is not None:
        ratio = daily['week_total'] / week_total if week_total else 0
        for person in result['techs'] + result['advisors']:
            if person['goal'] is not None:
                person['goal'] *= ratio
        for key in ('week_elapsed', 'week_total', 'month_elapsed', 'month_total'):
            result['calendar'][key] = daily[key]
        result['gp'].update(week=daily['gp_week'], mtd=daily['gp_mtd'], month_pace=daily['gp_month_pace'])
        result['gp']['daily_pace'] = daily['gp_mtd'] / daily['month_elapsed'] if daily['gp_mtd'] is not None and daily['month_elapsed'] else None
        result['tracking_from_paul'] = True
        result['basis'] = dict(gp='Paul’s Daily Business Analysis: saved daily GP actuals',
                               calendar='Paul’s daily allocation / shop working-day schedule',
                               actual_through=daily['actual_through'],
                               missing_actual_dates=daily['missing_actual_dates'], closed_dates=daily['closed_dates'])
        for row in result['kpis']:
            if row['label'] == 'GP per billed hour':
                row['actual'] = daily['gp_per_hour']
            if row['label'] == 'Cars posted':
                row['pace'] = row['actual'] / daily['month_elapsed'] * daily['month_total'] if row['actual'] is not None and daily['month_elapsed'] else None
        # Only service advisors appear here, matching the manager's two-advisor
        # section. Each margin is already computed in Paul's posted-sales sheet.
        result['advisors'] = [p for p in result['advisors'] if p['role'] == 'Service Advisor']
        for person in result['advisors']:
            person['actual'] = daily['advisor_margins'].get(person['name'].split()[0].lower())
        names = {'Robert Decker':'Robert', 'Michael Ricciardi':'Mike', 'Ryan Matson':'Ryan',
                 'Chris Rapp':'Vegas', 'Juan Alvarez':'Juan', 'Justin Zimmerman':'Justin'}
        for person in result['techs']:
            person['display_name'] = names.get(person['name'], person['name'])
        order = ['Robert','Mike','Ryan','Vegas','Juan','Justin']
        result['techs'].sort(key=lambda p: order.index(p['display_name']) if p['display_name'] in order else len(order))
    return result


def register(app, report_for):
    @app.get('/internal/manager-report')
    def manager_report_feed():
        token = os.getenv('MANAGER_REPORT_TOKEN', '')
        if not token or not hmac.compare_digest(request.headers.get('Authorization', ''), 'Bearer ' + token):
            abort(401)
        # Imports are local so contract tests can run without connecting to PNL.
        from src import db
        from src.config import load_config
        from . import metrics, paul
        from .manager_daily import daily_summary

        now = dt.datetime.now(ZoneInfo('America/New_York'))
        try:
            day = dt.date.fromisoformat(request.args.get('as_of', str(now.date())))
        except ValueError:
            abort(400)
        if day > now.date() or day < now.date() - dt.timedelta(days=366):
            abort(400)
        monday = day - dt.timedelta(days=day.weekday())
        with db.connect(load_config().database_url) as conn:
            # Enforce read-only for the accounting database too. report_for already
            # enforces read-only on the separate Tekmetric warehouse connection.
            conn.read_only = True
            data = report_for(conn, monday, day)
            books = paul.from_database(conn)
            grid = books.get(paul.DAILY, {}).get(paul.MONTHS[day.month - 1])
            if grid is None:
                abort(503, 'Daily Business Analysis month has not synced')
            daily = daily_summary(grid, day, monday, books[paul.DAILY].values())
        result = project(data, metrics.open_days(monday, monday + dt.timedelta(days=6)), now.isoformat(), daily)
        response = jsonify(result)
        response.headers['Cache-Control'] = 'no-store'
        return response
