# Sync Service

Фоновий сервіс, який кожні **30 секунд** опитує всі авто з центральної БД і зберігає отримані дані. Реалізує pull-модель відповідно до [DATA_CONTRACT.md](../../DATA_CONTRACT.md).

## Файли

| Файл | Роль |
|---|---|
| `main.py` | Точка входу. asyncio-цикл, паралельний sync всіх авто через `asyncio.gather` |
| `puller.py` | `VehiclePuller` — async context manager, httpx-клієнт для Outbound API авто |
| `writer.py` | Синхронні psycopg2-функції: batch insert, upsert, оновлення vehicles |
| `Dockerfile` | `python:3.11-slim`, запуск `python main.py` |
| `requirements.txt` | `httpx`, `psycopg2-binary`, `python-dotenv` |

## Цикл синхронізації

```
для кожного авто (паралельно — asyncio.gather):

  1. GET /status
       → оновити vehicles.last_seen_at, sync_status, software_version
       → timeout → sync_journal(status='timeout'); skip
       → error   → sync_journal(status='error');   skip

  2. GET /channels
       → upsert channel_config (phys_min/max → min_value/max_value)
       → некритично: збій не зупиняє sync

  3. Визначити pull-вікно:
       from = vehicles.last_sync_at ?? (now − PULL_WINDOW_SEC)
       to   = now

  4. GET /data?from=...&to=...
       → truncated=true → 10-хвилинні підзапити
       → gap > 24 год   → 1-годинні підзапити
       → batch INSERT measurements ON CONFLICT DO NOTHING
       → оновити vehicles.last_sync_at = to (тільки при успіху)

  5. GET /alarms?from=...&to=...
       → INSERT alarms_log ON CONFLICT (vehicle_id, alarm_id) UPDATE resolved_at
       → некритично: збій не зупиняє sync

  6. sync_journal(status='ok', rows_written=N)
```

## Gap-filling

`vehicles.last_sync_at` зберігає час останнього успішного pull. При наступному циклі `from = last_sync_at`, тобто весь gap між офлайн-сесіями підтягується автоматично.

Якщо крок 4 (data) упав — `last_sync_at` **не оновлюється**, і наступний цикл повторить той самий діапазон.

## Дедублікація

| Таблиця | Constraint | При повторній вставці |
|---|---|---|
| `measurements` | `UNIQUE (vehicle_id, channel_id, time)` | `DO NOTHING` |
| `alarms_log` | `UNIQUE (vehicle_id, alarm_id)` | `DO UPDATE SET resolved_at` |
| `channel_config` | `UNIQUE (vehicle_id, channel_id)` | `DO UPDATE SET name, unit, min_value, max_value, synced_at` |

## RLS

БД має `FORCE ROW LEVEL SECURITY`. Sync Service обходить RLS через:

```sql
-- на початку кожної транзакції (transaction-local, is_local=true)
SELECT set_config('app.user_role', 'superuser', true)
```

Реалізовано у `writer.py::_conn()`. Жоден запит не виконується поза цим контекстом.

## Конфігурація

Усі змінні беруться з `fleet_server/.env` (або з Docker-оточення):

| Змінна | Дефолт | Опис |
|---|---|---|
| `SYNC_INTERVAL_SEC` | `30` | Пауза між циклами (сек) |
| `PULL_TIMEOUT_SEC` | `10` | HTTP timeout для запитів до авто |
| `PULL_WINDOW_SEC` | `60` | Початкове вікно при першому sync (якщо `last_sync_at` = NULL) |
| `VEHICLE_DEFAULT_API_KEY` | — | `X-API-Key` — той самий що `OUTBOUND_API_KEY` на авто |
| `DB_HOST` | `localhost` | Хост PostgreSQL (`postgres` у Docker) |
| `DB_PORT` | `5432` | |
| `DB_NAME` | `fleet` | |
| `DB_USER` | `fleet_app` | |
| `DB_PASSWORD` | — | |

`VEHICLE_DEFAULT_API_KEY` використовується для всіх авто, у яких `vehicles.api_key IS NULL`.
Для per-vehicle ключа — заповнити `vehicles.api_key` у БД.

## Запуск локально

```bash
cd fleet_server

# Встановити залежності (якщо ще немає у venv)
pip install httpx psycopg2-binary python-dotenv

# Переконатись що VEHICLE_DEFAULT_API_KEY заповнений у .env
# та збігається з OUTBOUND_API_KEY на auto_telemetry

cd sync
python main.py
```

Приклад виводу:

```
2026-02-23 10:00:00 [INFO] sync: Sync service starting  interval=30s  timeout=10.0s  window=60s
2026-02-23 10:00:00 [INFO] sync: Starting sync cycle for 3 vehicle(s)…
2026-02-23 10:00:01 [INFO] sync: [Truck-01] online  sw=1.1.0  db_ok=True
2026-02-23 10:00:01 [INFO] sync: [Truck-01] wrote 1500 measurements  window=60s
2026-02-23 10:00:01 [WARNING] sync: [Truck-02] timeout on /status
2026-02-23 10:00:01 [INFO] sync: Cycle done in 2.3s — sleeping 27.7s
```

## Docker

```bash
# Запуск усього стеку (разом з api, postgres, grafana, nginx)
cd fleet_server
docker compose up -d sync

# Логи
docker compose logs -f sync
```

Сервіс `sync` в `docker-compose.yml` не відкриває жодного порту — тільки вихідні з'єднання до авто через WireGuard VPN.
