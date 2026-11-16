import datetime as dt
from contextlib import contextmanager
import functools
import hmac
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
import requests

from .model import dashboard, validate_goals

LOG = logging.getLogger(__name__)
TZ = ZoneInfo('America/New_York')


class SourceUnavailable(Exception):
    pass


class PNLClient:
    def __init__(self):
        self.lock = threading.Lock()
        self.cached = {}

    def read(self, day, force=False):
        with self.lock:
            entry = self.cached.get(day)
            if entry and not force and time.monotonic() - entry[0] < 60:
                return entry[1]
            base = os.getenv('PNL_REPORT_URL', '').rstrip('/')
            token = os.getenv('PNL_REPORT_TOKEN', '')
            if not base or not token:
                raise SourceUnavailable('The P&L connection has not been configured yet.')
            parsed = urlparse(base)
            if parsed.scheme not in ('https', 'http') or (parsed.scheme == 'http' and
                    not (parsed.hostname or '').endswith('.railway.internal') and parsed.hostname not in ('localhost', '127.0.0.1')):
                raise SourceUnavailable('The P&L connection URL must use HTTPS or Railway private networking.')
            try:
                response = requests.get(base + '/internal/manager-report', params={'as_of': day},
                                        headers={'Authorization': 'Bearer ' + token}, timeout=(5, 240), allow_redirects=False)
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError('Unexpected status')
                data = response.json()
                if data.get('schema_version') != 1 or data.get('as_of') != day:
                    raise ValueError('Unsupported P&L response')
                dashboard(data, {})  # Validate the contract before replacing the cache.
            except (requests.RequestException, ValueError, KeyError, TypeError):
                LOG.warning('P&L manager feed unavailable; no source values returned to client')
                raise SourceUnavailable('The P&L report is unavailable. Check its connection or try again shortly.') from None
            self.cached = {day: (time.monotonic(), data)}
            return data


def create_app(config=None, source=None):
    app = Flask(__name__)
    production = bool(os.getenv('RAILWAY_ENVIRONMENT'))
    secret = os.getenv('MANAGER_SECRET_KEY')
    if production and not secret:
        raise RuntimeError('MANAGER_SECRET_KEY is required in production')
    app.config.update(SECRET_KEY=secret or secrets.token_hex(32), SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=production,
                      MAX_CONTENT_LENGTH=32_768,
                      PERMANENT_SESSION_LIFETIME=dt.timedelta(hours=12),
                      GOALS_PATH=os.getenv('MANAGER_GOALS_PATH', 'data/manager-goals.sqlite3'))
    if config:
        app.config.update(config)
    client = source or PNLClient()

    @contextmanager
    def connection():
        path = Path(app.config['GOALS_PATH'])
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=10)
        try:
            with conn:
                conn.execute('CREATE TABLE IF NOT EXISTS goals (name TEXT PRIMARY KEY, value REAL NOT NULL)')
                yield conn
        finally:
            conn.close()

    def signed_in(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get('ok'):
                if request.path.startswith('/api/'):
                    return jsonify(error='Please sign in again.'), 401
                return redirect(url_for('login'))
            return view(*args, **kwargs)
        return wrapped

    def csrf():
        token = session.get('csrf')
        supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf', '')
        if not token or not hmac.compare_digest(token, supplied):
            abort(400, 'Refresh this page before saving.')

    def as_of():
        today = dt.datetime.now(TZ).date()
        try:
            day = dt.date.fromisoformat(request.args.get('as_of') or str(today))
        except ValueError:
            abort(400, 'Invalid date.')
        if day > today or day < today - dt.timedelta(days=366):
            abort(400, 'Choose a date within the last year.')
        return day.isoformat()

    def get_view(force=False):
        data = client.read(as_of(), force=force)
        with connection() as conn:
            personal = dict(conn.execute('SELECT name, value FROM goals'))
        return dashboard(data, personal)

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        return response

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        session.setdefault('csrf', secrets.token_hex(32))
        error = None
        if request.method == 'POST':
            csrf()
            expected = os.getenv('MANAGER_PASSWORD', '')
            user = os.getenv('MANAGER_USERNAME', 'manager')
            if expected and hmac.compare_digest(request.form.get('username', ''), user) and hmac.compare_digest(request.form.get('password', ''), expected):
                session.clear()
                session.update(ok=True, csrf=secrets.token_hex(32))
                session.permanent = True
                return redirect(url_for('index'))
            error = 'Sign-in failed. Check your username and password.'
        return render_template('login.html', error=error)

    @app.post('/logout')
    @signed_in
    def logout():
        csrf()
        session.clear()
        return redirect(url_for('login'))

    @app.get('/')
    @signed_in
    def index():
        day = as_of()
        return render_template('index.html', as_of=day, today=str(dt.datetime.now(TZ).date()))

    @app.get('/api/report')
    @signed_in
    def report():
        try:
            return jsonify(get_view(force=request.args.get('refresh') == '1'))
        except SourceUnavailable as exc:
            return jsonify(error=str(exc)), 503

    @app.post('/api/goals')
    @signed_in
    def save_goals():
        csrf()
        try:
            data = client.read(as_of())
            allowed = {f'{key}:{p["name"]}' for key in ('techs', 'advisors') for p in data[key]}
            values = validate_goals(request.get_json(), allowed)
            with connection() as conn:
                # Only replace the currently displayed people's optional goals.
                conn.executemany('DELETE FROM goals WHERE name = ?', [(k,) for k in allowed])
                conn.executemany('INSERT INTO goals(name, value) VALUES (?, ?)', values.items())
            return jsonify(saved=True)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except SourceUnavailable as exc:
            return jsonify(error=str(exc)), 503

    @app.get('/health')
    def health():
        return jsonify(status='ok')

    return app


app = create_app()
