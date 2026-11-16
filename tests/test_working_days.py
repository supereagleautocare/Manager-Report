from copy import deepcopy

import pytest

from manager.model import dashboard
from manager.working_days import validate
from test_manager import app, source, sign_in


def dated(source):
    source['as_of']='2026-11-11'
    return source


def test_auto_calendar_already_displays_difference_from_week_at_a_glance(source):
    data=dashboard(dated(source),{})
    assert data['source']['calendar']['month_total']==19
    assert 'manager report 19, Week at a Glance notes 21' in data['calendar_settings']['note']
    assert data['calendar_settings']['applied']=={}


def test_overrides_recalculate_all_pace_without_mutating_pnl(source):
    dated(source)
    original=deepcopy(source)
    data=dashboard(source,{},dict(month_total=21,month_elapsed=7,week_total=4,week_elapsed=2))
    assert data['gp_rows'][0]['pace']==48000/7*21
    assert data['gp_rows'][1]['pace']==48000/7*4
    assert data['gp_rows'][2]['actual']==48000/7
    assert data['gp_rows'][0]['goal']==125400
    assert data['gp_rows'][1]['goal']==125400/21*4
    assert data['techs'][0]['actual']==17.6
    assert data['techs'][0]['pace']==17.6/2*4
    assert data['techs'][0]['goal']==16
    assert data['advisors'][0]['goal']==16500*4/5
    assert data['kpis'][2]['pace']==100/7*21
    assert source==original


def test_matching_notes_removes_difference_note(source):
    data=dashboard(dated(source),{},dict(month_total=21))
    assert data['calendar_settings']['note'] is None
    assert data['calendar_settings']['applied']=={'month_total':21}


@pytest.mark.parametrize('payload',[
    {'month_total':0},{'month_total':31},{'month_total':19.5},{'month_total':True},
    {'week_total':8},{'week_total':2},{'week_elapsed':4},{'month_elapsed':12},
    {'month_elapsed':-1},{'month_total':'nan'},{'month_total':'inf'},{'month_total':[]},
    {'unknown':1},[],None,{'month_total':7,'month_elapsed':8}
])
def test_invalid_or_impossible_counts_are_rejected(source,payload):
    with pytest.raises(ValueError):
        validate(payload,source['calendar'],'2026-11-11')


def test_zero_elapsed_is_allowed_without_division_errors(source):
    data=dashboard(dated(source),{},dict(week_elapsed=0,month_elapsed=0))
    assert data['gp_rows'][0]['pace'] is None
    assert data['gp_rows'][1]['pace'] is None
    assert data['techs'][0]['pace'] is None


def test_expired_override_falls_back_with_clear_note(source):
    data=dashboard(dated(source),{},dict(month_total=7))
    assert data['source']['calendar']['month_total']==19
    assert 'could not be applied' in data['calendar_settings']['conflict']
    assert data['calendar_settings']['saved']=={'month_total':7}


def test_authenticated_scoped_persistence_and_reset(app):
    client=app.test_client()
    assert client.post('/api/working-days',json={}).status_code==401
    token=sign_in(client)
    assert client.post('/api/working-days',json={}).status_code==400
    headers={'X-CSRF-Token':token}
    endpoint='/api/working-days?as_of=2026-11-11'
    payload=dict(month_total=21,week_total=4,month_elapsed=7,week_elapsed=2)
    assert client.post(endpoint,json=payload,headers=headers).status_code==200
    other=app.test_client();sign_in(other)
    day=other.get('/api/report?as_of=2026-11-11').json
    assert day['calendar_settings']['saved']==payload
    assert day['gp_rows'][0]['pace']==48000/7*21
    next_day=other.get('/api/report?as_of=2026-11-12').json
    assert next_day['calendar_settings']['saved']=={'month_total':21,'week_total':4}
    other_week=other.get('/api/report?as_of=2026-11-02').json
    assert other_week['calendar_settings']['saved']=={'month_total':21}
    assert client.post(endpoint,json={'week_elapsed':4},headers=headers).status_code==400
    assert other.get('/api/report?as_of=2026-11-11').json['calendar_settings']['saved']==payload
    assert client.post(endpoint,json={},headers=headers).status_code==200
    assert other.get('/api/report?as_of=2026-11-11').json['calendar_settings']['saved']=={}
    assert other.get('/api/report?as_of=2026-11-12').json['source']['calendar']['month_total']==19
