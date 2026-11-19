import copy
import datetime as dt
import importlib.util
from pathlib import Path

import pytest
from flask import Flask

from manager.app import create_app, PNLClient, SourceUnavailable
from manager.model import dashboard, validate_goals

spec = importlib.util.spec_from_file_location('pnl_manager_feed', Path(__file__).parents[1] / 'integration/pnl_manager_feed.py')
feed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feed)


@pytest.fixture
def source():
    # Synthetic contract fixture. These are not shop production numbers.
    return dict(schema_version=1, as_of=str(dt.date.today()), generated_at='2026-11-11T12:00:00-05:00',
                freshness={'tekmetric': '2026-11-11T11:00:00-05:00'}, tracking_from_paul=True,
                week_at_a_glance_calendar=dict(week_elapsed=3,week_total=5,month_elapsed=8,month_total=21),
                calendar=dict(week_start='2026-11-09', week_elapsed=3, week_total=5, month_elapsed=8, month_total=19),
                gp=dict(week=18000, mtd=48000, month_goal=125400, month_pace=100000),
                kpis=[dict(label='Average repair order',kind='money',actual=477,goal=600),
                      dict(label='Close rate',kind='pct',actual=.34,goal=.50),
                      dict(label='Cars posted',kind='num',actual=100,goal=440,pace=237.5)],
                techs=[dict(name='Robert',actual=17.6,goal=20),dict(name='Mike',actual=30,goal=40)],
                advisors=[dict(name='Enoch',role='Service Advisor',actual=12000,sales=20000,goal=16500)])


def test_pace_uses_source_working_days_and_keeps_paul_projection(source):
    data = dashboard(source, {})
    assert data['gp_rows'][0]['pace'] == 100000  # Not our own MTD projection.
    assert data['gp_rows'][1]['pace'] == 30000
    assert data['gp_rows'][1]['goal'] == 33000
    assert data['gp_rows'][2]['actual'] == 6000
    assert data['techs'][0]['pace'] == pytest.approx(17.6 / 3 * 5)
    assert data['kpis'][1]['gap'] == pytest.approx(-.16)
    assert data['kpis'][2]['gap'] == 237.5 - 440
    assert data['advisors'][0]['actual'] == 12000
    assert data['advisors'][0]['sales'] == 20000
    assert data['totals']['advisors']['sales'] == 20000
    source['calendar'].update(week_total=4, month_total=20)
    source['gp']['month_goal'] = 120000
    updated = dashboard(source, {})
    assert updated['gp_rows'][1]['goal'] == 24000
    assert updated['gp_rows'][1]['pace'] == 24000


def test_missing_values_zero_goals_and_personal_goals(source):
    source['gp'].update(month_goal=None, month_pace=None)
    source['calendar']['week_elapsed'] = 0
    source['advisors'][0]['goal'] = None
    data = dashboard(source, {'techs:Robert': 0})
    assert data['gp_rows'][0]['gap'] is None
    assert data['gp_rows'][1]['pace'] is None
    assert data['advisors'][0]['gap'] is None
    assert data['techs'][0]['personal'] == 0
    assert data['totals']['advisors']['goal'] is None


def test_mtd_shop_gp_pace_is_consistent_across_all_periods(source):
    source['calendar']['month_total'] = 19
    source['gp'].update(mtd=38549.47, month_pace=38549.47 / 8 * 19, daily_pace=38549.47 / 8)
    data=dashboard(source,{})
    assert data['gp_rows'][0]['pace']==pytest.approx(91554.99125)
    assert data['gp_rows'][1]['pace']==pytest.approx(24093.41875)
    assert data['gp_rows'][2]['actual']==pytest.approx(4818.68375)


def test_daily_gp_matches_thirteen_weekday_average(source):
    month_gp=53783.28
    source['calendar'].update(month_elapsed=13,month_total=19,week_total=5)
    source['gp'].update(mtd=month_gp,daily_pace=month_gp/13,
                        month_pace=month_gp/13*19)
    data=dashboard(source,{})
    assert data['gp_rows'][0]['pace']==pytest.approx(month_gp/13*19)
    assert data['gp_rows'][1]['pace']==pytest.approx(month_gp/13*5)
    assert data['gp_rows'][2]['actual']==pytest.approx(4137.175384615385)


def test_manager_can_set_shop_goals_beside_pnl_goals(source):
    data=dashboard(source,{'shop:Monthly gross profit':110000,'kpis:Average repair order':500,'kpis:Cars posted':250})
    monthly=data['gp_rows'][0]
    assert monthly['goal']==125400 and monthly['personal']==110000
    assert monthly['personal_gap']==100000-110000  # Monthly pace vs manager target.
    aro=data['kpis'][0]
    assert aro['goal']==600 and aro['personal_gap']==477-500  # Rate: actual vs target.
    cars=data['kpis'][2]
    assert cars['personal_gap']==237.5-250  # Count: month pace vs target.
    assert data['kpis'][1]['personal'] is None and data['kpis'][1]['personal_gap'] is None


def test_alias_keeps_persistent_goal_identity_and_missing_advisor_data(source):
    source['techs'][0].update(name='Chris Rapp',display_name='Vegas')
    source['advisors'][0]['actual']=None
    data=dashboard(source,{'techs:Chris Rapp':30,'advisors:Enoch':16500})
    assert data['techs'][0]['label']=='Vegas'
    assert data['techs'][0]['goal_key']=='techs:Chris Rapp'
    assert data['techs'][0]['personal']==30
    assert data['advisors'][0]['gap'] is None
    assert data['advisors'][0]['personal_gap'] is None
    assert data['totals']['advisors']['actual'] is None


def test_reference_is_only_a_comparison_and_never_replaces_actuals(source):
    source['as_of']='2026-11-11'
    source['techs'][0].update(name='Robert Decker',display_name='Robert')
    data=dashboard(source,{})
    row=data['reconciliation']['rows'][0]
    assert row['reference']==17.6
    assert row['calculated']==pytest.approx(17.6/3*5)
    assert row['difference']!=0
    assert data['techs'][0]['actual']==17.6
    source['as_of']='2026-11-12'
    assert dashboard(source,{})['reconciliation'] is None


@pytest.mark.parametrize('value', ['nan','inf',-1,True,'no',1000001,[],{}])
def test_goal_validation(value):
    with pytest.raises(ValueError):
        validate_goals({'techs:Robert':value},{'techs:Robert'})


def test_feed_projects_only_safe_fields(source):
    report = dict(start='2026-11-09', end=source['as_of'], days_open=3,
                  month={'start':'2026-11-01','end':'2026-11-30','days_open':19,'days_worked':8},
                  freshness=source['freshness'], totals_mtd={'close_ratio':.34}, goals={'close_ratio':.5},
                  techs={'each':[{'name':'Robert','hours_turned':17.6,'hours_goal_week':20,'total_pay':999}]},
                  advisors={'each':[{'name':'Enoch','role':'Service Advisor','gp':12000,'net_sales':20000,'gp_goal':9900}]},
                  raw_customer='must never appear', front={'tracking_from_paul':True,'scoreboard':[
                      {'label':label,'week':18000,'mtd':48000,'mtd_goal':125400,'tracking':100000}
                      for label in ['Gross profit','Average ticket','Average quote','GP per billed hour','Cars posted']]})
    result = feed.project(report,5,'now')
    assert result['techs'][0]['goal'] == 20
    assert result['advisors'][0]['goal'] == 16500
    assert result['advisors'][0]['actual'] == 12000
    assert result['advisors'][0]['sales'] == 20000
    assert result['week_at_a_glance_calendar']['month_total']==19
    assert 'raw_customer' not in str(result)
    assert 'total_pay' not in str(result)
    assert result['gp']['month_pace'] == 100000
    assert len(result['kpis']) == 4
    assert all(row['label'] != 'Close rate' for row in result['kpis'])
    saved_daily=dict(week_elapsed=3,week_total=5,month_elapsed=8,month_total=19,
                     gp_week=15972.8,gp_mtd=38549.47,gp_month_pace=38549.47/8*19,
                     gp_per_hour=141.585,advisor_margins={'enoch':8161.62},
                     actual_through='2026-11-11',missing_actual_dates=[],closed_dates=['2026-11-26','2026-11-27'])
    daily_result=feed.project(report,5,'now',saved_daily)
    assert daily_result['calendar']['month_total']==19
    assert daily_result['gp']['mtd']==38549.47
    assert daily_result['gp']['daily_pace']==pytest.approx(4818.68375)
    assert daily_result['advisors'][0]['actual']==8161.62
    assert daily_result['advisors'][0]['goal']==16500
    assert next(row for row in daily_result['kpis'] if row['label']=='GP per billed hour')['actual']==141.585


def test_feed_requires_dedicated_token(monkeypatch):
    app = Flask(__name__)
    feed.register(app, lambda *_: pytest.fail('Unauthenticated request reached report'))
    client = app.test_client()
    assert client.get('/internal/manager-report').status_code == 401
    monkeypatch.setenv('MANAGER_REPORT_TOKEN','secret-token')
    assert client.get('/internal/manager-report',headers={'Authorization':'Bearer wrong'}).status_code == 401


@pytest.fixture
def app(tmp_path,monkeypatch,source):
    monkeypatch.setenv('MANAGER_PASSWORD','test-password')
    class FakeSource:
        def read(self,day,force=False):
            result=copy.deepcopy(source)
            result['as_of']=day
            return result
    return create_app({'TESTING':True,'SECRET_KEY':'test-key','GOALS_PATH':str(tmp_path/'goals.sqlite3')},FakeSource())


def sign_in(client):
    client.get('/login')
    with client.session_transaction() as session:
        csrf=session['csrf']
    response=client.post('/login',data={'username':'manager','password':'test-password','csrf':csrf})
    assert response.status_code == 302
    with client.session_transaction() as session:
        return session['csrf']


def test_auth_csrf_goal_persistence_and_removal(app):
    client=app.test_client()
    assert client.get('/api/report').status_code == 401
    assert client.get('/').status_code == 302
    csrf=sign_in(client)
    assert client.get('/').status_code == 200
    assert client.get('/api/report').json['gp_rows'][1]['goal'] == 33000
    assert client.post('/api/goals',json={'techs:Robert':45}).status_code == 400
    headers={'X-CSRF-Token':csrf}
    assert client.post('/api/goals',json={'unknown':99},headers=headers).status_code == 400
    assert client.post('/api/goals',json={'techs:Robert':45},headers=headers).status_code == 200
    other=app.test_client()
    sign_in(other)
    assert other.get('/api/report').json['techs'][0]['personal'] == 45
    assert other.get('/api/report').json['techs'][0]['goal'] == 20
    assert client.post('/api/goals',json={'techs:Robert':''},headers=headers).status_code == 200
    assert other.get('/api/report').json['techs'][0]['personal'] is None
    shop={'shop:Monthly gross profit':150000,'kpis:Average repair order':550}
    assert client.post('/api/goals',json=shop,headers=headers).status_code == 200
    report=other.get('/api/report').json
    assert report['gp_rows'][0]['personal']==150000 and report['gp_rows'][0]['goal']==125400
    assert report['kpis'][0]['personal']==550
    assert client.post('/api/goals',json={'kpis:Made up':1},headers=headers).status_code == 400
    assert client.get('/api/report?as_of=not-a-date').status_code == 400
    assert client.get('/api/report?as_of=2099-01-01').status_code == 400
    assert client.post('/logout',data={'csrf':csrf}).status_code == 302
    assert client.get('/api/report').status_code == 401


def test_client_never_returns_stale_source_on_error(monkeypatch,source):
    monkeypatch.setenv('PNL_REPORT_URL','https://pnl.example')
    monkeypatch.setenv('PNL_REPORT_TOKEN','token')
    class Response:
        status_code=200
        def raise_for_status(self): pass
        def json(self): return source
    monkeypatch.setattr('manager.app.requests.get',lambda *a,**k:Response())
    client=PNLClient()
    assert client.read(source['as_of']) == source
    def fail(*a,**kw):
        import requests
        raise requests.ConnectionError('Do not leak secrets')
    monkeypatch.setattr('manager.app.requests.get',fail)
    with pytest.raises(SourceUnavailable,match='unavailable'):
        client.read(source['as_of'],force=True)


def test_unavailable_source_is_clear_and_health_is_independent(tmp_path):
    class Broken:
        def read(self,*args,**kwargs): raise SourceUnavailable('P&L unavailable')
    app=create_app({'TESTING':True,'GOALS_PATH':str(tmp_path/'db')},Broken())
    client=app.test_client()
    with client.session_transaction() as session: session['ok']=True
    assert client.get('/health').status_code == 200
    assert client.get('/api/report').status_code == 503
    assert client.get('/api/report').json == {'error':'P&L unavailable'}
