# Тестування Sync Service на одному ПК

Інструкція для запуску `fleet_server/sync` та `auto_telemetry/outbound`
одночасно на одному комп'ютері без WireGuard VPN.

**Схема:**
```
[auto_telemetry/outbound :8001]  ←pull─  [fleet_server/sync]
         localhost                               localhost
```

---

## Передумови

- PostgreSQL запущений локально (порт 5432)
- БД `telemetry` існує (auto_telemetry)
- БД `fleet` існує та схема застосована (fleet_server)
- Python-залежності встановлені в обох проектах

Перевірити БД:
```powershell
psql -U postgres -c "\l" | findstr "telemetry fleet"
```

---

## Крок 1 — Зареєструвати тестове авто у fleet DB (одноразово)

```powershell
cd F:\fleet_server\fleet_server
python seed_local_test.py
```

Скрипт додає авто з параметрами:

| Поле | Значення |
|---|---|
| `name` | Local Test Vehicle |
| `vpn_ip` | `127.0.0.1` |
| `api_port` | `8001` |
| `api_key` | `dev_outbound_key_change_in_production` |

Idempotent — при повторному запуску просто оновлює існуючий запис.

---

## Крок 2 — Запустити auto_telemetry outbound API

**Термінал 1:**

```powershell
cd F:\fleet_server\auto_telemetry
python -m uvicorn outbound.main:app --host 0.0.0.0 --port 8001
```

Перевірити що відповідає (PowerShell):

```powershell
Invoke-WebRequest -Uri http://localhost:8001/status `
  -Headers @{"X-API-Key"="dev_outbound_key_change_in_production"} |
  Select-Object -ExpandProperty Content
```

Очікувана відповідь:
```json
{"vehicle_id_hint":"vehicle-dev","software_version":"unknown","uptime_sec":5,...}
```

### (Опційно) Запустити симулятор для генерації даних

Якщо в БД `telemetry` немає реальних вимірювань — у **Терміналі 2** запустіть симулятор:

```powershell
cd F:\fleet_server\auto_telemetry
python simulators/test_server_minimal.py
```

Або collector з Modbus-симулятором ET7017:
```powershell
# Термінал 2а — симулятор Modbus пристрою
python simulators/et7017_simulator.py

# Термінал 2б — collector (читає з симулятора → записує в telemetry БД)
python -m uvicorn collector.main:app
```

---

## Крок 3 — Запустити fleet_server sync

**Термінал 3:**

```powershell
cd F:\fleet_server\fleet_server\sync
pip install -r requirements.txt   # якщо ще не встановлено
python main.py
```

### Очікуваний вивід при успіху

```
2026-02-23 10:00:00 [INFO] sync: Sync service starting  interval=30s  timeout=10.0s  window=60s
2026-02-23 10:00:00 [INFO] sync: Starting sync cycle for 1 vehicle(s)…
2026-02-23 10:00:01 [INFO] sync: [Local Test Vehicle] online  sw=unknown  db_ok=True
2026-02-23 10:00:01 [INFO] sync: [Local Test Vehicle] wrote 1500 measurements  window=60s
2026-02-23 10:00:01 [INFO] sync: Cycle done in 1.2s — sleeping 28.8s
```

### Якщо даних немає (порожня БД `telemetry`)

```
[INFO] sync: [Local Test Vehicle] online  sw=unknown  db_ok=True
[INFO] sync: Cycle done in 0.8s — sleeping 29.2s
```
→ `wrote 0 measurements` або рядок відсутній — це нормально, запустіть симулятор.

---

## Крок 4 — Перевірка результату

**PowerShell:**

```powershell
python -c "
import psycopg2
conn = psycopg2.connect(host='localhost', dbname='fleet', user='fleet_app', password='devpassword')
cur = conn.cursor()
cur.execute(\"SET LOCAL app.user_role='superuser'\")

cur.execute('SELECT COUNT(*) FROM measurements')
print('measurements:', cur.fetchone()[0])

cur.execute('SELECT COUNT(*) FROM alarms_log')
print('alarms_log: ', cur.fetchone()[0])

cur.execute('SELECT COUNT(*) FROM channel_config')
print('channel_config:', cur.fetchone()[0])

cur.execute('''
    SELECT name, sync_status, last_sync_at::text, software_version
    FROM vehicles WHERE vpn_ip = %s::inet
''', ('127.0.0.1',))
row = cur.fetchone()
print('vehicle:', row)

cur.execute('''
    SELECT status, rows_written, started_at::text
    FROM sync_journal ORDER BY started_at DESC LIMIT 3
''')
print('sync_journal (last 3):')
for r in cur.fetchall(): print(' ', r)
conn.close()
"
```

---

## Типові помилки

| Симптом | Причина | Рішення |
|---|---|---|
| `[Local Test Vehicle] error on /status: Connection refused` | outbound не запущений | Запустити Термінал 1 |
| `[Local Test Vehicle] timeout on /status` | outbound завис або порт зайнятий | Перевірити `netstat -an \| findstr 8001` |
| `[Local Test Vehicle] error on /status: 401` | ключі не збігаються | Перевірити `VEHICLE_DEFAULT_API_KEY` в `.env` та `OUTBOUND_API_KEY` в `auto_telemetry/.env` |
| `Failed to read vehicles from DB` | fleet DB недоступна | Перевірити PostgreSQL, запустити `seed_local_test.py` |
| `wrote 0 measurements` щоразу | в `telemetry` немає даних | Запустити симулятор |

---

## Зупинка

`Ctrl+C` у кожному терміналі.

Тестове авто залишається в fleet DB — при наступному тестуванні достатньо знову запустити sync (кроки 2 і 3). Якщо потрібно видалити:

```powershell
python -c "
import psycopg2
conn = psycopg2.connect(host='localhost', dbname='fleet', user='fleet_app', password='devpassword')
cur = conn.cursor()
cur.execute(\"SET LOCAL app.user_role='superuser'\")
cur.execute(\"DELETE FROM vehicles WHERE vpn_ip = '127.0.0.1'::inet\")
conn.commit()
conn.close()
print('Видалено')
"
```
