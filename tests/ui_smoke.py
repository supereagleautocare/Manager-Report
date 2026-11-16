"""Optional browser smoke check: python tests/ui_smoke.py (requires Playwright)."""
import copy
import datetime as dt
import os
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).parents[1]))
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from manager.app import create_app, SourceUnavailable
from test_manager import source


def main():
    fixture = source.__wrapped__()
    # Reproduce the reported confusing case: no current-week posted GP, with
    # valid daily pace from MTD actuals. The UI must not display "Actual —".
    fixture['gp'].update(week=None,daily_pace=6000,month_pace=114000)
    fixture['kpis'].insert(1,dict(label='Average quote',kind='money',actual=1409,goal=1200))
    fixture['kpis'].insert(3,dict(label='GP per billed hour',kind='money',actual=141,goal=150))
    fixture['kpis'] = [row for row in fixture['kpis'] if row['label'] != 'Close rate']
    fixture['techs'].extend([dict(name=name,actual=20+i,goal=40) for i,name in enumerate(['Ryan','Vegas','Juan','Justin'])])
    class FakeSource:
        broken = False
        def read(self, day, force=False):
            if self.broken:
                raise SourceUnavailable('P&L unavailable')
            result = copy.deepcopy(fixture)
            result['as_of'] = day
            return result
    adapter = FakeSource()
    os.environ['MANAGER_PASSWORD'] = 'test-password'
    artifacts = Path('artifacts')
    artifacts.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        app = create_app({'TESTING': True, 'GOALS_PATH': str(Path(directory) / 'goals.db')}, adapter)
        server = make_server('127.0.0.1', 0, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        errors = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={'width': 1440, 'height': 1100})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.get_by_label('Username').fill('manager')
                page.get_by_label('Password').fill('test-password')
                page.get_by_role('button', name='Sign in', exact=True).click()
                page.locator('#report').wait_for(state='visible')
                assert page.locator('#gp-cards').inner_text().count('$114,000') == 1
                assert page.locator('#gp-cards .gp-line').count()==3
                assert 'Actual' not in page.locator('#gp-cards').inner_text()
                assert 'GP earned this month: $48,000'==page.locator('#gp-earned').inner_text()
                assert '$30,000' in page.locator('#gp-cards .gp-line').nth(1).inner_text()
                page.get_by_role('button', name='Edit goals').click()
                page.locator('input[data-key="techs:Robert"]').fill('45')
                page.get_by_role('button', name='Save manager goals').click()
                page.get_by_text('Manager goals saved.', exact=True).wait_for()
                page.reload()
                page.locator('#report').wait_for(state='visible')
                assert '45.00 h' in page.locator('#personal-summary').inner_text()
                page.screenshot(path=str(artifacts/'manager-desktop.png'), full_page=True)
                page.pdf(path=str(artifacts/'manager-print.pdf'), prefer_css_page_size=True, print_background=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(artifacts/'manager-mobile.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.goto(f'http://127.0.0.1:{server.server_port}/?as_of=2026-11-11')
                page.locator('#reconciliation').wait_for(state='visible')
                assert page.locator('#reference-rows tr').count() >= 10
                page.screenshot(path=str(artifacts/'manager-reference-test.png'),full_page=True)
                assert 'Week at a Glance notes 21' in page.locator('#calendar-note').inner_text()
                page.get_by_role('button',name='Edit working days',exact=True).click()
                page.get_by_label('Month working days',exact=True).fill('21')
                page.get_by_role('button',name='Save working days',exact=True).click()
                page.get_by_text('Working days saved. Pace calculations updated.',exact=True).wait_for()
                assert 'Month: day 8 / 21' in page.locator('#working-days').inner_text()
                assert 'Working days differ' not in page.locator('#calendar-note').inner_text()
                assert '$126,000' in page.locator('#gp-cards').inner_text()
                page.reload(); page.locator('#report').wait_for(state='visible')
                assert 'Month: day 8 / 21' in page.locator('#working-days').inner_text()
                page.get_by_role('button',name='Edit working days',exact=True).click()
                assert page.get_by_label('Month working days',exact=True).input_value()=='21'
                page.get_by_label('Month working days',exact=True).fill('20')
                page.get_by_label('Week working days',exact=True).fill('4')
                page.get_by_role('button',name='Save working days',exact=True).click()
                page.get_by_text('Working days saved. Pace calculations updated.',exact=True).wait_for()
                assert 'manager report 20, Week at a Glance notes 21' in page.locator('#calendar-note').inner_text()
                assert 'Week: day 3 / 4' in page.locator('#working-days').inner_text()
                page.screenshot(path=str(artifacts/'working-days-editor.png'),full_page=True)
                page.emulate_media(media='print')
                assert page.locator('#calendar-note').is_visible()
                assert not page.locator('#working-days-form').is_visible()
                page.emulate_media(media='screen')
                page.get_by_role('button',name='Use P&L days',exact=True).click()
                page.get_by_text('Working days reset to P&L.',exact=True).wait_for()
                assert 'Month: day 8 / 19' in page.locator('#working-days').inner_text()
                adapter.broken = True
                page.get_by_role('button', name='Refresh', exact=True).click()
                page.get_by_text('P&L unavailable The numbers below are from the last successful refresh.', exact=True).wait_for()
                assert page.locator('#report').is_visible()
                # An expected 503 is logged by the browser after the failure check.
                assert not [e for e in errors if '503' not in e], errors
                browser.close()
        finally:
            server.shutdown()
    print('Browser checks passed: sign-in, report, goals, editable working days, persistence, recalculation, Week at a Glance notes, reset, mobile, print, source failure.')


if __name__ == '__main__':
    main()
