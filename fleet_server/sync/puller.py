"""
Async HTTP client for pulling telemetry data from one vehicle's Outbound API.

Порт: 8001
Контракт: DATA_CONTRACT.md (корінь монорепо)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)


def _iso(dt: datetime) -> str:
    """datetime → ISO8601 UTC рядок з міліскундами."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)  # нормалізуємо з будь-якого TZ у UTC
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def _split_windows(
    from_: datetime, to: datetime, step: timedelta
) -> list[tuple[datetime, datetime]]:
    """Розбити часовий діапазон на рівні вікна."""
    windows = []
    cur = from_
    while cur < to:
        nxt = min(cur + step, to)
        windows.append((cur, nxt))
        cur = nxt
    return windows


class VehiclePuller:
    """Async HTTP клієнт для одного авто (async context manager)."""

    def __init__(self, vehicle: dict, api_key: str, timeout: float) -> None:
        base_url = f"http://{vehicle['vpn_ip']}:{vehicle['api_port']}"
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-Key": api_key, "Accept-Encoding": "gzip"},
            timeout=timeout,
        )
        self._name = vehicle.get('name', str(vehicle.get('id', '?')))

    async def __aenter__(self) -> VehiclePuller:
        return self

    async def __aexit__(self, *_) -> None:
        await self._client.aclose()

    # ── Ендпоінти ─────────────────────────────────────────────────────────────

    async def pull_status(self) -> dict:
        """GET /status → dict зі станом авто."""
        r = await self._client.get('/status')
        r.raise_for_status()
        return r.json()

    async def pull_channels(self) -> list[dict]:
        """GET /channels → список конфігурацій каналів."""
        r = await self._client.get('/channels')
        r.raise_for_status()
        return r.json()

    async def pull_data(self, from_: datetime, to: datetime) -> list[dict]:
        """GET /data → всі рядки вимірювань у вікні.

        Якщо gap > 24 год — автоматично розбиває на 1-годинні підзапити.
        Якщо відповідь truncated=true — розбиває на 10-хвилинні підзапити.
        """
        if (to - from_).total_seconds() > 86400:
            all_rows: list[dict] = []
            for wf, wt in _split_windows(from_, to, timedelta(hours=1)):
                all_rows.extend(await self._fetch_data_window(wf, wt))
            return all_rows
        return await self._fetch_data_window(from_, to)

    async def _fetch_data_window(
        self, from_: datetime, to: datetime
    ) -> list[dict]:
        r = await self._client.get(
            '/data', params={'from': _iso(from_), 'to': _iso(to)}
        )
        r.raise_for_status()
        body = r.json()
        if not body.get('truncated'):
            return body['rows']

        # Відповідь обрізана: розбиваємо на 10-хвилинні підзапити
        log.debug(
            '[%s] /data truncated for %s..%s — splitting into 10-min windows',
            self._name, _iso(from_), _iso(to),
        )
        all_rows: list[dict] = []
        for wf, wt in _split_windows(from_, to, timedelta(minutes=10)):
            all_rows.extend(await self._fetch_data_window(wf, wt))
        return all_rows

    async def pull_alarms(self, from_: datetime, to: datetime) -> list[dict]:
        """GET /alarms → список тривог у вікні."""
        r = await self._client.get(
            '/alarms', params={'from': _iso(from_), 'to': _iso(to)}
        )
        r.raise_for_status()
        return r.json()
