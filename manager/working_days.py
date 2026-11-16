"""Manager-only calendar overrides, with the original PNL calendar preserved."""
import calendar
from copy import deepcopy
import datetime as dt

FIELDS = ('week_elapsed', 'week_total', 'month_elapsed', 'month_total')
LABELS = dict(week_elapsed='Week days elapsed', week_total='Week working days',
              month_elapsed='Month days elapsed', month_total='Month working days')


def scopes(day):
    day = dt.date.fromisoformat(day)
    monday = day - dt.timedelta(days=day.weekday())
    return dict(week_total=f'week:{monday}:total', month_total=f'month:{day:%Y-%m}:total',
                week_elapsed=f'date:{day}:week_elapsed', month_elapsed=f'date:{day}:month_elapsed')


def validate(payload, source, day):
    if not isinstance(payload, dict) or set(payload) - set(FIELDS):
        raise ValueError('Unknown working-day field. Refresh the report and try again.')
    date = dt.date.fromisoformat(day)
    maximum = dict(week_total=7, week_elapsed=date.weekday()+1,
                   month_total=calendar.monthrange(date.year, date.month)[1], month_elapsed=date.day)
    values = {}
    for key, value in payload.items():
        if value is None or value == '':
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError(f'{LABELS[key]} must be a whole number.')
        try:
            numeric = float(value)
            integer = int(numeric)
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f'{LABELS[key]} must be a whole number.') from None
        minimum = 1 if key.endswith('total') else 0
        if integer != numeric or not minimum <= integer <= maximum[key]:
            raise ValueError(f'{LABELS[key]} must be a whole number from {minimum} to {maximum[key]}.')
        values[key] = integer
    effective = {key: values.get(key, source[key]) for key in FIELDS}
    for period in ('week', 'month'):
        if effective[f'{period}_elapsed'] > effective[f'{period}_total']:
            raise ValueError(f'{period.capitalize()} days elapsed cannot exceed its total working days.')
    return values


def apply(source, saved):
    effective = deepcopy(source)
    original = {key: source['calendar'][key] for key in FIELDS}
    conflict = None
    try:
        valid = validate(saved, original, source['as_of'])
    except ValueError as exc:
        valid = {}
        conflict = f'Saved working days could not be applied: {exc} Using P&L days until corrected.'
    days = effective['calendar']
    days.update(valid)
    if valid:
        gp = effective['gp']
        daily_gp = gp['mtd'] / days['month_elapsed'] if gp['mtd'] is not None and days['month_elapsed'] else None
        gp.update(daily_pace=daily_gp, month_pace=daily_gp * days['month_total'] if daily_gp is not None else None)
        for row in effective['kpis']:
            if row['label'] == 'Cars posted':
                row['pace'] = row['actual'] / days['month_elapsed'] * days['month_total'] if row['actual'] is not None and days['month_elapsed'] else None
        week_ratio = days['week_total'] / original['week_total'] if original['week_total'] else None
        for key in ('techs', 'advisors'):
            for person in effective[key]:
                if person['goal'] is not None and week_ratio is not None:
                    person['goal'] *= week_ratio
    baseline = source.get('week_at_a_glance_calendar')
    differences = [f"{LABELS[key]}: manager report {days[key]}, Week at a Glance notes {baseline[key]}"
                   for key in FIELDS if baseline and key in baseline and days[key] != baseline[key]]
    settings = dict(defaults=original, saved=saved, applied=valid, conflict=conflict,
                    week_at_a_glance=baseline, differences=differences,
                    note='Working days differ from the Week at a Glance notes. ' + '; '.join(differences) + '.' if differences else None)
    return effective, settings
