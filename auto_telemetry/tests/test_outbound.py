"""
Автоматичні тести Outbound API (outbound/main.py).

Запуск з кореня auto_telemetry/:
    pytest tests/test_outbound.py -v

Не потребує запущеного сервера і живої БД —
psycopg2 та _port_listening мокуються через unittest.mock.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from outbound.main import app

# ── Константи ─────────────────────────────────────────────────────────────────

KEY   = 'test-key'
AUTH  = {'X-API-Key': KEY}
NOKEY = {}
BADKEY = {'X-API-Key': 'wrong-key'}

_TS     = datetime(2026, 2, 22, 10, 30, 0, 123000, tzinfo=timezone.utc)
_TS_STR = '2026-02-22T10:30:00.123Z'

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def client():
    return TestClient(app, raise_server_exceptions=True)


# ── Хелпер: мок psycopg2 connection ──────────────────────────────────────────

def _mock_conn(rows=None, one=None):
    """
    Повертає мок psycopg2 connection.

    rows — що повертає cur.fetchall() (для /channels, /data/latest, /data, /alarms)
    one  — що повертає cur.fetchone() (для /status: кортеж (timestamp,))
    """
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = rows if rows is not None else []
    cur.fetchone.return_value = one

    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


# ── Автентифікація ────────────────────────────────────────────────────────────

class TestAuth:
    """X-API-Key перевіряється на кожному ендпоінті."""

    def test_missing_key_returns_422(self, client):
        """FastAPI повертає 422 якщо обов'язковий header відсутній."""
        assert client.get('/status').status_code == 422

    def test_wrong_key_returns_401(self, client):
        assert client.get('/status', headers=BADKEY).status_code == 401

    def test_correct_key_passes_auth(self, client):
        with patch('outbound.main.psycopg2.connect', return_value=_mock_conn(one=(None,))), \
             patch('outbound.main._port_listening', return_value=False):
            r = client.get('/status', headers=AUTH)
        assert r.status_code == 200

    def test_auth_applied_to_channels(self, client):
        assert client.get('/channels', headers=BADKEY).status_code == 401

    def test_auth_applied_to_data_latest(self, client):
        assert client.get('/data/latest', headers=BADKEY).status_code == 401

    def test_auth_applied_to_data(self, client):
        url = '/data?from=2026-02-22T10:00:00Z&to=2026-02-22T10:05:00Z'
        assert client.get(url, headers=BADKEY).status_code == 401

    def test_auth_applied_to_alarms(self, client):
        url = '/alarms?from=2026-02-01T00:00:00Z&to=2026-03-01T00:00:00Z'
        assert client.get(url, headers=BADKEY).status_code == 401


# ── GET /status ───────────────────────────────────────────────────────────────

class TestStatus:

    def _get(self, client, *, one=(None,), port=False, db_fail=False):
        if db_fail:
            cm_connect = patch('outbound.main.psycopg2.connect',
                               side_effect=Exception('db error'))
        else:
            cm_connect = patch('outbound.main.psycopg2.connect',
                               return_value=_mock_conn(one=one))
        with cm_connect, patch('outbound.main._port_listening', return_value=port):
            return client.get('/status', headers=AUTH)

    def test_response_has_all_fields(self, client):
        r = self._get(client)
        assert r.status_code == 200
        assert set(r.json()) == {
            'vehicle_id_hint', 'software_version', 'uptime_sec',
            'collector_running', 'agent_running', 'db_ok', 'last_measurement_at',
        }

    def test_vehicle_id_hint(self, client):
        assert self._get(client).json()['vehicle_id_hint'] == 'test-vehicle'

    def test_db_ok_true_on_success(self, client):
        assert self._get(client).json()['db_ok'] is True

    def test_db_ok_false_on_connect_error(self, client):
        r = self._get(client, db_fail=True)
        assert r.status_code == 200       # /status не повертає 503, а db_ok=false
        assert r.json()['db_ok'] is False

    def test_last_measurement_at_none_when_no_data(self, client):
        assert self._get(client, one=(None,)).json()['last_measurement_at'] is None

    def test_last_measurement_at_formatted(self, client):
        assert self._get(client, one=(_TS,)).json()['last_measurement_at'] == _TS_STR

    def test_port_listening_reflected_in_running_flags(self, client):
        body = self._get(client, port=True).json()
        assert body['collector_running'] is True
        assert body['agent_running'] is True

    def test_uptime_sec_is_non_negative_int(self, client):
        uptime = self._get(client).json()['uptime_sec']
        assert isinstance(uptime, int)
        assert uptime >= 0


# ── GET /channels ─────────────────────────────────────────────────────────────

class TestChannels:

    _ROW = {
        'channel_id': 1,
        'name': 'Тиск масла',
        'unit': 'bar',
        'raw_min': 6400.0,
        'raw_max': 32000.0,
        'phys_min': 0.0,
        'phys_max': 10.0,
        'signal_type': 'analog_420',
        'enabled': True,
        'updated_at': _TS,
    }

    def test_returns_list(self, client):
        with patch('outbound.main.psycopg2.connect', return_value=_mock_conn(rows=[self._ROW])):
            r = client.get('/channels', headers=AUTH)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_channel_fields_present(self, client):
        with patch('outbound.main.psycopg2.connect', return_value=_mock_conn(rows=[self._ROW])):
            ch = client.get('/channels', headers=AUTH).json()[0]
        assert ch['channel_id'] == 1
        assert ch['name'] == 'Тиск масла'
        assert ch['unit'] == 'bar'
        assert ch['phys_min'] == 0.0
        assert ch['phys_max'] == 10.0
        assert ch['signal_type'] == 'analog_420'
        assert ch['enabled'] is True
        assert ch['updated_at'] == _TS_STR

    def test_empty_db_returns_empty_list(self, client):
        with patch('outbound.main.psycopg2.connect', return_value=_mock_conn(rows=[])):
            assert client.get('/channels', headers=AUTH).json() == []

    def test_db_unavailable_returns_503(self, client):
        with patch('outbound.main.psycopg2.connect', side_effect=Exception('no db')):
            assert client.get('/channels', headers=AUTH).status_code == 503


# ── GET /data/latest ──────────────────────────────────────────────────────────

class TestDataLatest:

    _ROWS = [
        {'channel_id': 1, 'value': 4.72, 'time': _TS},
        {'channel_id': 2, 'value': None, 'time': _TS},
    ]

    def test_returns_list(self, client):
        with patch('outbound.main.psycopg2.connect', return_value=_mock_conn(rows=self._ROWS)):
            r = client.get('/data/latest', headers=AUTH)
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_value_and_time_formatted(self, client):
        with patch('outbound.main.psycopg2.connect', return_value=_mock_conn(rows=self._ROWS)):
            body = client.get('/data/latest', headers=AUTH).json()
        assert body[0] == {'channel_id': 1, 'value': 4.72,  'time': _TS_STR}
        assert body[1] == {'channel_id': 2, 'value': None,   'time': _TS_STR}

    def test_empty_db_returns_empty_list(self, client):
        with patch('outbound.main.psycopg2.connect', return_value=_mock_conn(rows=[])):
            assert client.get('/data/latest', headers=AUTH).json() == []


# ── GET /data ─────────────────────────────────────────────────────────────────

class TestData:

    _URL   = '/data?from=2026-02-22T10:00:00Z&to=2026-02-22T10:05:00Z'
    _ROWS  = [
        {'channel_id': 1, 'value': 4.72, 'time': _TS},
        {'channel_id': 2, 'value': 3.10, 'time': _TS},
    ]

    def test_valid_request_structure(self, client):
        with patch('outbound.main.psycopg2.connect', return_value=_mock_conn(rows=self._ROWS)):
            r = client.get(self._URL, headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body['count'] == 2
        assert body['truncated'] is False
        assert len(body['rows']) == 2
        assert 'from' in body and 'to' in body

    def test_row_fields(self, client):
        with patch('outbound.main.psycopg2.connect', return_value=_mock_conn(rows=self._ROWS)):
            row = client.get(self._URL, headers=AUTH).json()['rows'][0]
        assert row == {'channel_id': 1, 'value': 4.72, 'time': _TS_STR}

    def test_from_equals_to_returns_400(self, client):
        r = client.get('/data?from=2026-02-22T10:00:00Z&to=2026-02-22T10:00:00Z', headers=AUTH)
        assert r.status_code == 400

    def test_from_after_to_returns_400(self, client):
        r = client.get('/data?from=2026-02-22T10:05:00Z&to=2026-02-22T10:00:00Z', headers=AUTH)
        assert r.status_code == 400

    def test_missing_from_returns_422(self, client):
        r = client.get('/data?to=2026-02-22T10:05:00Z', headers=AUTH)
        assert r.status_code == 422

    def test_missing_to_returns_422(self, client):
        r = client.get('/data?from=2026-02-22T10:00:00Z', headers=AUTH)
        assert r.status_code == 422

    def test_truncated_true_when_limit_exceeded(self, client):
        # DB повертає 2 рядки, але limit=1 → truncated
        with patch('outbound.main.psycopg2.connect', return_value=_mock_conn(rows=self._ROWS)):
            body = client.get(self._URL + '&limit=1', headers=AUTH).json()
        assert body['truncated'] is True
        assert body['count'] == 1
        assert len(body['rows']) == 1

    def test_channel_id_filter_is_accepted(self, client):
        with patch('outbound.main.psycopg2.connect', return_value=_mock_conn(rows=self._ROWS[:1])):
            r = client.get(self._URL + '&channel_id=1', headers=AUTH)
        assert r.status_code == 200

    def test_db_unavailable_returns_503(self, client):
        with patch('outbound.main.psycopg2.connect', side_effect=Exception('no db')):
            assert client.get(self._URL, headers=AUTH).status_code == 503


# ── GET /alarms ───────────────────────────────────────────────────────────────

class TestAlarms:

    _URL  = '/alarms?from=2026-02-01T00:00:00Z&to=2026-03-01T00:00:00Z'
    _ROWS = [
        {
            'alarm_id': 42,
            'channel_id': 3,
            'severity': 'critical',
            'message': 'Перевищення порогу: 98.2 bar',
            'triggered_at': _TS,
            'resolved_at': None,
        }
    ]

    def test_valid_request(self, client):
        with patch('outbound.main.psycopg2.connect', return_value=_mock_conn(rows=self._ROWS)):
            r = client.get(self._URL, headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        alarm = body[0]
        assert alarm['alarm_id'] == 42
        assert alarm['channel_id'] == 3
        assert alarm['severity'] == 'critical'
        assert alarm['triggered_at'] == _TS_STR
        assert alarm['resolved_at'] is None

    def test_from_after_to_returns_400(self, client):
        r = client.get('/alarms?from=2026-03-01T00:00:00Z&to=2026-02-01T00:00:00Z', headers=AUTH)
        assert r.status_code == 400

    def test_missing_from_returns_422(self, client):
        r = client.get('/alarms?to=2026-03-01T00:00:00Z', headers=AUTH)
        assert r.status_code == 422

    def test_unresolved_only_accepted(self, client):
        with patch('outbound.main.psycopg2.connect', return_value=_mock_conn(rows=[])):
            r = client.get(self._URL + '&unresolved_only=true', headers=AUTH)
        assert r.status_code == 200

    def test_severity_null_when_no_rule(self, client):
        """alarm_id без rule_id → severity=null (NULL у JOIN)."""
        row = {**self._ROWS[0], 'severity': None}
        with patch('outbound.main.psycopg2.connect', return_value=_mock_conn(rows=[row])):
            alarm = client.get(self._URL, headers=AUTH).json()[0]
        assert alarm['severity'] is None

    def test_empty_result(self, client):
        with patch('outbound.main.psycopg2.connect', return_value=_mock_conn(rows=[])):
            assert client.get(self._URL, headers=AUTH).json() == []

    def test_db_unavailable_returns_503(self, client):
        with patch('outbound.main.psycopg2.connect', side_effect=Exception('no db')):
            assert client.get(self._URL, headers=AUTH).status_code == 503
