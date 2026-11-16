import datetime as dt
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('manager_daily', Path(__file__).parents[1] / 'integration/pnl_manager_daily.py')
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)


def grid():
    header=[None,None,None,None,'Sales projections','Gross Profit','Net Sales','Receipts','Hours Billed','Enoch Margin','Morgan Margin']
    rows=[header]
    for day in range(1,31):
        date=dt.date(2026,11,day)
        if date.weekday()>4: continue
        opened=day not in (26,27)
        # Synthetic complete actuals through the 11th, then forecasts.
        actual=day<=11 and opened
        rows.append([1 if opened else None,None,str(date),date.strftime('%A'),1000 if opened else 0,
                     100 if actual else 999,200 if actual else 888,250 if actual else 0,2 if actual else 0,
                     40 if actual else 999,60 if actual else 999])
    return SimpleNamespace(values=rows)


def test_workbook_calendar_and_actuals_exclude_forecasts():
    result=daily.daily_summary(grid(),dt.date(2026,11,11),dt.date(2026,11,9))
    assert result['month_total']==19
    assert result['month_elapsed']==8
    assert result['week_elapsed']==3 and result['week_total']==5
    assert result['gp_mtd']==800 and result['gp_week']==300
    assert result['gp_month_pace']==1900
    assert result['advisor_margins']=={'enoch':120,'morgan':180}
    assert result['gp_per_hour']==50
    assert result['closed_dates']==['2026-11-26','2026-11-27']
    assert result['missing_actual_dates']==[]


def test_arrived_forecast_is_not_an_actual():
    result=daily.daily_summary(grid(),dt.date(2026,11,16),dt.date(2026,11,16))
    assert result['gp_week'] is None
    assert result['advisor_margins']['enoch'] is None
    assert result['gp_mtd']==800
    assert result['actual_through']=='2026-11-11'
    assert result['missing_actual_dates']==['2026-11-12','2026-11-13','2026-11-16']


def test_short_holiday_week():
    result=daily.daily_summary(grid(),dt.date(2026,11,25),dt.date(2026,11,23))
    assert result['week_total']==3 and result['week_elapsed']==3


def test_missing_headers_fail_instead_of_silently_using_wrong_cells():
    with pytest.raises(ValueError):
        daily.daily_summary(SimpleNamespace(values=[['bad header']]),dt.date(2026,11,11),dt.date(2026,11,9))


def test_cross_month_week_reads_adjacent_month_schedule():
    november=grid()
    # Nov 30 + Dec 1-4: Dec 4 is closed in this synthetic schedule.
    december=SimpleNamespace(values=[november.values[0]]+[
        [1 if day<4 else None,None,f'2026-12-0{day}','weekday',1000 if day<4 else 0,0,0,0,0,0,0]
        for day in range(1,5)])
    result=daily.daily_summary(november,dt.date(2026,11,30),dt.date(2026,11,30),[december])
    assert result['week_total']==4
