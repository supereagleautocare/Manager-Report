"""Presentation only. Source calculations and working days belong to PNL."""
import math
from .reference import comparison


def divide(value, divisor):
    return value / divisor if value is not None and divisor else None


def multiply(value, factor):
    return value * factor if value is not None and factor is not None else None


def metric(label, kind, actual, goal, pace=None, **extra):
    comparison = actual if pace is None else pace
    return dict(label=label, kind=kind, actual=actual, goal=goal, pace=pace,
                gap=comparison - goal if comparison is not None and goal is not None else None, **extra)


def dashboard(source, personal):
    days = source['calendar']
    worked, week_days = days['week_elapsed'], days['week_total']
    gp = source['gp']
    daily_goal = divide(gp['month_goal'], days['month_total'])
    daily_pace = gp.get('daily_pace', divide(gp['week'], worked))
    # The manager template uses the same MTD daily average for monthly, weekly
    # and daily shop GP pace. Individual staff pace still uses WTD actuals.
    gp_rows = [
        metric('Monthly gross profit', 'money', gp['mtd'], gp['month_goal'], gp['month_pace']),
        metric('Weekly gross profit', 'money', gp['week'], multiply(daily_goal, week_days),
               multiply(daily_pace, week_days)),
        metric('Daily gross profit · average', 'money', daily_pace, daily_goal),
    ]
    kpis = [metric(x['label'], x['kind'], x['actual'], x['goal'], x.get('pace')) for x in source['kpis']]
    techs, advisors = [], []
    for section, key, output in [('techs', 'hours', techs), ('advisors', 'gp', advisors)]:
        for person in source[section]:
            target = personal.get(f"{section}:{person['name']}")
            output.append(metric(person.get('display_name', person['name']), 'hours' if key == 'hours' else 'money', person['actual'],
                                 person['goal'], multiply(divide(person['actual'], worked), week_days),
                                 personal=target, role=person.get('role', ''), sales=person.get('sales'), goal_key=f"{section}:{person['name']}",
                                 personal_gap=(multiply(divide(person['actual'], worked), week_days) - target)
                                 if target is not None and worked and person['actual'] is not None else None))
    totals = {}
    for key, rows in [('techs', techs), ('advisors', advisors)]:
        # Sum the displayed people, never compare all writers with only advisors' goals.
        total_actual = sum(r['actual'] for r in rows) if rows and all(r['actual'] is not None for r in rows) else None
        totals[key] = metric('Total shown', 'hours' if key == 'techs' else 'money',
                             total_actual,
                             sum(r['goal'] for r in rows) if rows and all(r['goal'] is not None for r in rows) else None,
                             multiply(divide(total_actual, worked), week_days))
        if key == 'advisors':
            totals[key]['sales'] = sum(r['sales'] for r in rows) if rows and all(r['sales'] is not None for r in rows) else None
    result = dict(source=source, gp_rows=gp_rows, kpis=kpis, techs=techs, advisors=advisors, totals=totals)
    result['reconciliation'] = comparison(result)
    return result


def validate_goals(payload, allowed):
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ValueError('Unknown goal field. Refresh the report and try again.')
    result = {}
    for key, value in payload.items():
        if value in ('', None):
            continue
        if isinstance(value, bool):
            raise ValueError('Goals must be positive numbers or zero.')
        try:
            number = float(value)
        except (ValueError, TypeError):
            raise ValueError('Goals must be positive numbers or zero.') from None
        if not math.isfinite(number) or not 0 <= number <= 1_000_000:
            raise ValueError('Goals must be between 0 and 1,000,000.')
        result[key] = number
    return result
