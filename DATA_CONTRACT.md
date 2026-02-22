# Auto Telemetry ↔ Fleet Server — Контракт синхронізації даних

**Версія:** 1.3
**Дата:** 2026-02-22
**Репозиторії:** `auto_telemetry` (машина) · `fleet_server` (сервер)

### Changelog
| Версія | Зміна |
|---|---|
| 1.0 | Початковий контракт |
| 1.1 | Карта сервісів, `software_version`, `agent_running` у `/status`, розмежування систем автентифікації |
| 1.2 | **Виправлення протиріч з кодом:** (1) порт `api_port` 8080→8001; (2) `/alarms` потребує JOIN з `alarm_rules` для `severity`; (3) `alarm_id` тип INTEGER→BIGINT |
| 1.3 | Стиснення відповідей gzip (`GZipMiddleware`, `minimum_size=500`); Fleet Server повинен надсилати `Accept-Encoding: gzip` |

---

## Карта сервісів на машині

На кожній машині (`auto_telemetry`) одночасно працюють чотири сервіси, якими керує `watchdog.py`. Цей контракт стосується **тільки Outbound API** (порт 8001).

```
Машина (auto_telemetry) — watchdog.py
├── collector/main.py        :—     Modbus → PostgreSQL + ZeroMQ PUB
├── portal/main.py           :8000  Операторський UI (тільки локальна мережа установки)
├── outbound/main.py         :8001  ← ЦЕЙ КОНТРАКТ: pull від Fleet Server
└── agent/server.py          :9876  Окрема система: push оновлень від розробника
                                    (RSA-PSS автентифікація, не API-key)
```

> **Важливо:** Агент (порт 9876) і Outbound API (порт 8001) — **повністю незалежні системи** з різною автентифікацією та різними цілями. Не плутати.

**Перевірка ліцензії** виконується `watchdog.py` один раз при старті — до запуску будь-яких сервісів. Outbound API не перевіряє ліцензію самостійно.

---

## Загальна схема взаємодії

```
[auto_telemetry / outbound API :8001]    [fleet_server / sync]
         HTTP over WireGuard VPN    ←pull─── puller.py  (кожні 30 сек)
              ↑                                   ↓
         measurements              →  fleet DB: measurements
         alarms_log                →  fleet DB: alarms_log
         channel_config            →  fleet DB: channel_config
```

**Принцип:** Fleet Server завжди **pull**. Машина нічого не пушить.
**Транспорт:** HTTP/1.1 over WireGuard VPN (`10.0.0.x`).
**Автентифікація:** статичний API-ключ у заголовку `X-API-Key` (VPN ізолює мережу, але ключ потрібен щоб ідентифікувати авторизований Fleet Server серед інших клієнтів VPN).
**Стиснення:** Outbound API стискає відповіді gzip для тіл > 500 байт. Fleet Server **повинен** надсилати заголовок `Accept-Encoding: gzip` — `httpx` робить це автоматично за замовчуванням.

---

## Автентифікація

Кожен запит від Fleet Server → машина містить заголовок:

```
X-API-Key: <secret>
```

Секрет зберігається:
- На машині: `OUTBOUND_API_KEY` у `.env`
- На сервері: `VEHICLE_DEFAULT_API_KEY` у `.env` (або `vehicles.api_key` у БД для per-vehicle ключів)

При відсутності або неправильному ключі машина повертає `401 Unauthorized`.

> **Розмежування систем автентифікації на машині:**
>
> | Система | Метод | Ключ |
> |---|---|---|
> | Outbound API (цей контракт) | Pre-shared `X-API-Key` | `OUTBOUND_API_KEY` у `.env` |
> | Agent :9876 (оновлення від розробника) | RSA-PSS підпис timestamp | `UPDATE_SERVER_PUBLIC_KEY_PEM` вбудований в `agent/authenticator.py` |
> | Ліцензія | RSA-PSS підпис fingerprint | `_PUBLIC_KEY_PEM` вбудований у `license/_core.pyd` |
>
> Це три незалежні механізми. `OUTBOUND_API_KEY` не має жодного стосунку до RSA-ключів.

---

## Base URL

```
http://{vpn_ip}:{api_port}
```

Приклад: `http://10.0.0.11:8001`

`api_port` зберігається в таблиці `vehicles.api_port`.

> ⚠️ **Критично:** `ws_live.py` у fleet_server використовує `vehicles.api_port` для виклику `/data/latest`:
> ```python
> vehicle_url = f"http://{vehicle['vpn_ip']}:{vehicle['api_port']}/data/latest"
> ```
> При додаванні машини через адмін-панель (`/admin?tab=vehicles`) поле **"Порт"** потрібно вказувати **8001** (не 8080 — це дефолт у коді, але він неправильний для цього проекту).
>
> Відповідно у `fleet_server/api/models/vehicle.py` і `db/01_init.sql` замінити дефолт:
> ```python
> # models/vehicle.py
> api_port: int = 8001          # було 8080
> ```
> ```sql
> -- db/01_init.sql
> api_port INTEGER NOT NULL DEFAULT 8001,  -- було 8080
> ```
> Portal на машині (порт 8000) і Agent (порт 9876) — окремі сервіси, Outbound API — **8001**.

---

## Ендпоінти

### 1. `GET /status`

Перевірка доступності машини та мета-інформація. Використовується Sync Service для визначення `online/offline`, оновлення `last_seen_at`, а також для відстеження версії ПЗ на кожній машині.

**Відповідь `200 OK`:**
```json
{
  "vehicle_id_hint": "truck-01",
  "software_version": "1.1.0",
  "uptime_sec": 3600,
  "collector_running": true,
  "agent_running": true,
  "db_ok": true,
  "last_measurement_at": "2026-02-22T10:30:00.000Z"
}
```

| Поле | Тип | Опис |
|---|---|---|
| `vehicle_id_hint` | string | локальна мітка машини (лише для логів) |
| `software_version` | string | версія з `version.txt` у корені проекту |
| `collector_running` | bool | чи працює процес Collector |
| `agent_running` | bool | чи працює агент оновлень (порт 9876) |
| `db_ok` | bool | чи доступна локальна БД |
| `last_measurement_at` | ISO8601 UTC \| null | час останнього запису в measurements |

Fleet Server зберігає `software_version` у таблиці `vehicles` для відстеження розгортання оновлень по всьому парку.

---

### 2. `GET /channels`

Конфігурація каналів. Fleet Server зберігає копію для відображення назв/одиниць.  
Викликається при кожному циклі sync — порівнює `synced_at` і оновлює якщо є зміни.

**Відповідь `200 OK`:**
```json
[
  {
    "channel_id": 1,
    "name": "Тиск масла",
    "unit": "bar",
    "raw_min": 6400.0,
    "raw_max": 32000.0,
    "phys_min": 0.0,
    "phys_max": 10.0,
    "signal_type": "analog_420",
    "enabled": true,
    "updated_at": "2026-02-20T08:00:00.000Z"
  }
]
```

**Маппінг → fleet DB `channel_config`:**

| Outbound поле | Fleet DB поле | Примітка |
|---|---|---|
| `channel_id` | `channel_id` | як є |
| `name` | `name` | як є |
| `unit` | `unit` | як є |
| `phys_min` | `min_value` | перейменування |
| `phys_max` | `max_value` | перейменування |
| `updated_at` | `synced_at` | Fleet записує час своєї sync-операції |
| *(implicit)* | `vehicle_id` | додається Sync Service |

---

### 3. `GET /data/latest`

Останнє значення по кожному каналу. Використовується WebSocket Live (`ws_live.py`) — опитується кожні 2 секунди.

**Відповідь `200 OK`:**
```json
[
  {
    "channel_id": 1,
    "value": 4.72,
    "time": "2026-02-22T10:30:00.123Z"
  },
  {
    "channel_id": 2,
    "value": null,
    "time": "2026-02-22T10:30:00.123Z"
  }
]
```

> `value: null` — канал вимкнений або модуль недоступний.  
> Порядок елементів не гарантований — клієнт ідентифікує за `channel_id`.

**SQL на машині (реалізація):**
```sql
SELECT DISTINCT ON (channel_id)
    channel_id, value, time
FROM measurements
ORDER BY channel_id, time DESC;
```

---

### 4. `GET /data`

Вимірювання за часовим діапазоном. Основний endpoint для Sync Service.

**Query параметри:**

| Параметр | Тип | Обов'язковий | Опис |
|---|---|---|---|
| `from` | ISO8601 UTC | ✓ | початок діапазону (включно) |
| `to` | ISO8601 UTC | ✓ | кінець діапазону (виключно) |
| `channel_id` | int | — | фільтр по каналу (якщо не задано — всі) |
| `limit` | int | — | максимум рядків (default: 10000, max: 50000) |

**Приклад запиту:**
```
GET /data?from=2026-02-22T10:00:00Z&to=2026-02-22T10:01:00Z
```

**Відповідь `200 OK`:**
```json
{
  "from": "2026-02-22T10:00:00.000Z",
  "to":   "2026-02-22T10:01:00.000Z",
  "count": 2,
  "truncated": false,
  "rows": [
    {"channel_id": 1, "value": 4.72, "time": "2026-02-22T10:00:01.000Z"},
    {"channel_id": 2, "value": 3.10, "time": "2026-02-22T10:00:01.000Z"}
  ]
}
```

| Поле | Опис |
|---|---|
| `truncated` | `true` якщо `count` досяг `limit` — Sync Service повинен розбити запит на менші вікна |
| `rows` | відсортовані за `time ASC` |

**Маппінг → fleet DB `measurements`:**

| Outbound поле | Fleet DB поле | Примітка |
|---|---|---|
| `channel_id` | `channel_id` | як є |
| `value` | `value` | як є |
| `time` | `time` | як є |
| *(implicit)* | `vehicle_id` | додається Sync Service |

---

### 5. `GET /alarms`

Тривоги за часовим діапазоном.

**Query параметри:**

| Параметр | Тип | Обов'язковий | Опис |
|---|---|---|---|
| `from` | ISO8601 UTC | ✓ | за `triggered_at` |
| `to` | ISO8601 UTC | ✓ | |
| `unresolved_only` | bool | — | якщо `true` — тільки активні тривоги |

**Відповідь `200 OK`:**
```json
[
  {
    "alarm_id": 42,
    "channel_id": 3,
    "severity": "critical",
    "message": "Перевищення порогу: 98.2 bar (поріг: 90.0)",
    "triggered_at": "2026-02-22T10:15:30.000Z",
    "resolved_at": null
  }
]
```

> ⚠️ **Важливо:** У `auto_telemetry/db/01_init.sql` таблиця `alarms_log` **не має колонки `severity`** — вона є тільки в `alarm_rules`. Тому ендпоінт `/alarms` повинен робити JOIN:
>
> ```sql
> -- SQL на машині (реалізація)
> SELECT
>     al.id          AS alarm_id,   -- аліас: в таблиці поле називається 'id'
>     al.channel_id,
>     ar.severity,                  -- JOIN бо в alarms_log severity немає
>     al.message,
>     al.triggered_at,
>     al.resolved_at
> FROM alarms_log al
> LEFT JOIN alarm_rules ar ON ar.id = al.rule_id
> WHERE al.triggered_at >= %(from)s
>   AND al.triggered_at <  %(to)s
> ORDER BY al.triggered_at ASC
> ```
>
> Якщо тривога була створена без прив'язки до правила (`rule_id IS NULL`) — `severity` буде `null`. Fleet Server це приймає.

**Маппінг → fleet DB `alarms_log`:**

| Outbound поле | Fleet DB поле | Примітка |
|---|---|---|
| `alarm_id` | `alarm_id` | аліас від `alarms_log.id` (BIGINT) на машині |
| `channel_id` | `channel_id` | |
| `severity` | `severity` | отримується через JOIN з `alarm_rules` |
| `message` | `message` | |
| `triggered_at` | `triggered_at` | |
| `resolved_at` | `resolved_at` | null якщо активна |
| *(implicit)* | `vehicle_id` | додається Sync Service |

> ⚠️ **Тип `alarm_id`:** На машині `alarms_log.id` — `BIGSERIAL` (int8). У fleet_server `alarms_log.alarm_id` — `INTEGER` (int4, ліміт ~2.1 млрд). Для промислової системи з рідкими тривогами це не критично, але правильніше виправити у fleet_server:
> ```sql
> -- fleet_server/db/01_init.sql — виправити тип
> alarm_id    BIGINT      NOT NULL,   -- було INTEGER
> ```

> **Дедублікація:** Fleet Server перевіряє унікальність `(vehicle_id, alarm_id)` — при повторному отриманні тільки оновлює `resolved_at`.

---

## Поведінка Sync Service (fleet_server/sync)

### Цикл синхронізації (кожні 30 сек)

```
для кожної машини (паралельно):
  1. GET /status
     → оновити vehicles.last_seen_at, sync_status
     → якщо помилка: записати sync_journal(status='timeout'/'error'), перейти до наступної

  2. GET /channels
     → якщо updated_at змінився — upsert channel_config

  3. Визначити вікно pull:
     from = vehicles.last_sync_at ?? (now - 60s)
     to   = now

  4. GET /data?from=...&to=...
     → якщо truncated=true: розбити на 10-хвилинні вікна і повторити
     → batch insert у measurements
     → оновити vehicles.last_sync_at = to

  5. GET /alarms?from=...&to=...
     → upsert alarms_log (on conflict (vehicle_id, alarm_id) do update resolved_at)

  6. Записати sync_journal(status='ok', rows_written=N)
```

### Обробка збоїв та gap-filling

```
Машина була offline з T1 по T2 (> 30 сек):

При наступному підключенні:
  from = vehicles.last_sync_at  (= T1 — останній успішний sync)
  to   = now                    (= T2 + деякий час)

Весь gap T1..T2 буде завантажено за один або кілька запитів.
```

**Обмеження вікна:** якщо `to - from > 24 год` — Sync Service розбиває на вікна по 1 годині щоб уникнути `truncated=true` та перевантаження машини.

### Статуси в `sync_journal`

| status | Умова |
|---|---|
| `ok` | `/status` відповів і дані записані |
| `timeout` | HTTP timeout (машина не відповіла за `PULL_TIMEOUT_SEC`) |
| `error` | HTTP відповів але з помилкою (4xx/5xx), або помилка парсингу |

---

## Коди помилок Outbound API

| HTTP | Ситуація |
|---|---|
| `200` | OK |
| `400 Bad Request` | невалідні параметри (`from` > `to`, неправильний формат дати) |
| `401 Unauthorized` | відсутній або неправильний `X-API-Key` |
| `503 Service Unavailable` | локальна БД машини недоступна |

**Тіло помилки:**
```json
{"error": "invalid_params", "detail": "from must be before to"}
```

---

## Формати даних

### Часові мітки

Всі `time`/`triggered_at`/`resolved_at`/`updated_at` — **ISO 8601 UTC** з міліскундами:
```
2026-02-22T10:30:00.123Z
```

Машина зберігає UTC (`TIMESTAMPTZ`). Fleet Server зберігає UTC. Жодних local timezone.

### Числові значення

`value` — `float64` або `null`. Fleet Server зберігає `DOUBLE PRECISION`.  
Нормалізовані фізичні значення (вже після `normalizer.py`), не сирі raw регістри.

---

## Реалізація: Outbound API (auto_telemetry)

**Файл:** `outbound/main.py`  
**Запуск:** `uvicorn outbound.main:app --host 0.0.0.0 --port 8001`

```python
# outbound/main.py — скелет реалізації

from fastapi import FastAPI, Header, HTTPException, Query
from datetime import datetime, timezone
import psycopg2, os

app = FastAPI(title="Auto Telemetry Outbound API")

API_KEY = os.getenv("OUTBOUND_API_KEY", "")

def _check_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(401)

def _dsn():
    return (f"host={os.getenv('DB_HOST','localhost')} "
            f"dbname={os.getenv('DB_NAME','telemetry')} "
            f"user={os.getenv('DB_USER','telemetry')} "
            f"password={os.getenv('DB_PASSWORD','')}")

@app.get("/status")
def status(x_api_key: str = Header(...)):
    _check_key(x_api_key)
    # ...

@app.get("/channels")
def channels(x_api_key: str = Header(...)):
    _check_key(x_api_key)
    # SELECT channel_id, name, unit, phys_min, phys_max,
    #        signal_type, enabled, updated_at FROM channel_config WHERE enabled
    # (Fleet Sync Service сам перейменовує phys_min→min_value, phys_max→max_value при записі в DB)

@app.get("/data/latest")
def data_latest(x_api_key: str = Header(...)):
    _check_key(x_api_key)
    # SELECT DISTINCT ON (channel_id) channel_id, value, time
    # FROM measurements ORDER BY channel_id, time DESC

@app.get("/data")
def data(
    from_: datetime = Query(..., alias="from"),
    to: datetime    = Query(...),
    channel_id: int | None = Query(None),
    limit: int      = Query(10000, le=50000),
    x_api_key: str  = Header(...),
):
    _check_key(x_api_key)
    # SELECT channel_id, value, time FROM measurements
    # WHERE time >= from_ AND time < to
    # ORDER BY time ASC LIMIT limit+1  (для визначення truncated)

@app.get("/alarms")
def alarms(
    from_: datetime          = Query(..., alias="from"),
    to: datetime             = Query(...),
    unresolved_only: bool    = Query(False),
    x_api_key: str           = Header(...),
):
    _check_key(x_api_key)
    # SELECT al.id AS alarm_id, al.channel_id, ar.severity, al.message,
    #        al.triggered_at, al.resolved_at
    # FROM alarms_log al
    # LEFT JOIN alarm_rules ar ON ar.id = al.rule_id
    # WHERE al.triggered_at >= from_ AND al.triggered_at < to
    # (+ AND al.resolved_at IS NULL якщо unresolved_only)
```

---

## Реалізація: Sync Service (fleet_server/sync)

**Файли:** `sync/puller.py`, `sync/writer.py`, `sync/main.py`

```python
# sync/puller.py — скелет

import httpx
from datetime import datetime, timezone, timedelta

class VehiclePuller:
    def __init__(self, vehicle: dict, api_key: str, timeout: float):
        self.vehicle = vehicle
        self.base_url = f"http://{vehicle['vpn_ip']}:{vehicle['api_port']}"
        self.headers = {"X-API-Key": api_key}
        self.timeout = timeout

    async def pull_status(self):
        # GET /status → оновити last_seen_at, sync_status

    async def pull_channels(self):
        # GET /channels → upsert channel_config

    async def pull_data(self, from_: datetime, to: datetime):
        # GET /data?from=...&to=...
        # якщо truncated — рекурсивно по 10-хв вікнах

    async def pull_alarms(self, from_: datetime, to: datetime):
        # GET /alarms?from=...&to=...


# sync/writer.py — скелет

def write_measurements(conn, vehicle_id: str, rows: list[dict]):
    # batch INSERT INTO measurements (vehicle_id, channel_id, value, time)
    # VALUES %s ON CONFLICT DO NOTHING

def upsert_alarms(conn, vehicle_id: str, alarms: list[dict]):
    # INSERT INTO alarms_log (...) ON CONFLICT (vehicle_id, alarm_id)
    # DO UPDATE SET resolved_at = EXCLUDED.resolved_at

def upsert_channels(conn, vehicle_id: str, channels: list[dict]):
    # INSERT INTO channel_config (vehicle_id, channel_id, name, unit, ...)
    # ON CONFLICT (vehicle_id, channel_id) DO UPDATE SET ...
```

---

## Змінні середовища

### auto_telemetry `.env` (додати)

```env
# Outbound API (для Fleet Server pull)
OUTBOUND_API_KEY=<random-32-bytes-hex>
# Порт Outbound API (відрізняється від Portal :8000 та Agent :9876)
OUTBOUND_PORT=8001
```

> `OUTBOUND_API_KEY` — незалежний від ключів ліцензійної системи та RSA-ключів агента.  
> Це простий pre-shared secret тільки для автентифікації Fleet Server.

### auto_telemetry `config.txt` (додати)

```ini
# Outbound API для Fleet Server
OUTBOUND_PORT     = 8001
```

### fleet_server `.env` (додати)

```env
# Sync Service
SYNC_INTERVAL_SEC=30
PULL_TIMEOUT_SEC=10
PULL_WINDOW_SEC=60
# API ключ — той самий що OUTBOUND_API_KEY на машинах
# Можна один спільний для всіх машин або окремий на кожну (в таблиці vehicles.api_key)
VEHICLE_DEFAULT_API_KEY=<той самий ключ>
```

---

## Схема БД: зміни

### fleet_server — виправити дефолт `api_port` у `vehicles`

```sql
-- Виправити: дефолт 8080 → 8001 (Outbound API порт)
ALTER TABLE vehicles ALTER COLUMN api_port SET DEFAULT 8001;
```

Також у `fleet_server/api/models/vehicle.py`:
```python
api_port: int = 8001   # було 8080
```

### fleet_server — додати колонки до таблиці `vehicles`

```sql
ALTER TABLE vehicles ADD COLUMN api_key TEXT;
ALTER TABLE vehicles ADD COLUMN software_version TEXT;
ALTER TABLE vehicles ADD COLUMN last_sync_at TIMESTAMPTZ;
```

### fleet_server — виправити тип `alarm_id` у `alarms_log`

```sql
-- Машина зберігає alarms_log.id як BIGSERIAL (int8).
-- Fleet має зберігати alarm_id як BIGINT щоб уникнути переповнення.
ALTER TABLE alarms_log ALTER COLUMN alarm_id TYPE BIGINT;
```

### fleet_server — таблиця `measurements` (унікальність для ON CONFLICT)

```sql
ALTER TABLE measurements ADD CONSTRAINT measurements_unique
    UNIQUE (vehicle_id, channel_id, time);
```

### fleet_server — таблиця `alarms_log` (дедублікація)

```sql
ALTER TABLE alarms_log ADD CONSTRAINT alarms_log_vehicle_alarm_unique
    UNIQUE (vehicle_id, alarm_id);
```

---

## Checklist реалізації

### auto_telemetry (машина)
- [ ] Створити `outbound/main.py` з 5 ендпоінтами
- [ ] Додати `OUTBOUND_API_KEY` у `.env` та `OUTBOUND_PORT` у `config.txt`
- [ ] Створити `version.txt` у корені проекту (читається endpoint `/status`)
- [ ] Додати `outbound/requirements.txt` (`fastapi`, `uvicorn`, `psycopg2-binary`, `python-dotenv`)
- [ ] Додати сервіс `outbound` у `docker-compose.yml` (порт 8001, bind `0.0.0.0` — VPN мережа ізольована)
- [ ] Інтегрувати запуск `outbound` у `watchdog.py` четвертим процесом (після collector, portal, agent)
- [ ] Покрити ендпоінти unit-тестами з mock БД

### fleet_server (сервер)
- [ ] Реалізувати `sync/puller.py` — HTTP клієнт для всіх 5 ендпоінтів
- [ ] Реалізувати `sync/writer.py` — batch insert + upsert
- [ ] Реалізувати `sync/main.py` — asyncio loop, паралельний pull всіх машин
- [ ] Міграція БД: додати `software_version` до `vehicles`, унікальний індекс на `measurements`, constraint на `alarms_log`
- [ ] Зберігати `software_version` з `/status` у `vehicles.software_version` при кожному sync
- [ ] Додати `sync_journal` записи при кожному циклі
- [ ] Тестування gap-filling: зупинити машину на 5 хв, переконатись що дані підтягнулись
- [ ] Відображати `software_version` у Fleet UI (таблиця авто в `/admin`)
