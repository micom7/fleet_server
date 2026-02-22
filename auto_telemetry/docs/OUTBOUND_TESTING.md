# Тестування Outbound API

**Файл:** `outbound/main.py`
**Порт:** `8001`
**Контракт:** `DATA_CONTRACT.md` (корінь монорепо)

---

## Підготовка

### 1. Запуск сервісу

```bash
# З кореня auto_telemetry:
python run_dev.py --no-sims --no-collector --outbound

# Або напряму:
python -m uvicorn outbound.main:app --host 0.0.0.0 --port 8001
```

### 2. Змінна KEY та інструмент для запитів

> **Windows PowerShell:** `curl` — це аліас `Invoke-WebRequest`, не сумісний з Unix-прапорами.
> Усі команди нижче написані для **Git Bash**. Для PowerShell — окремий блок.

**Git Bash** — присвоєння без `$` і без пробілів навколо `=`:
```bash
KEY="dev_outbound_key_change_in_production"
curl -s -H "X-API-Key: $KEY" http://localhost:8001/status | python -m json.tool
```

**PowerShell** — `$KEY =` з пробілами (синтаксис PS), `curl.exe` замість `curl`:
```powershell
$KEY = "dev_outbound_key_change_in_production"
curl.exe -s -H "X-API-Key: $KEY" http://localhost:8001/status | python -m json.tool
```

**PowerShell без curl** — через `Invoke-WebRequest`:
```powershell
$KEY = "dev_outbound_key_change_in_production"
(Invoke-WebRequest http://localhost:8001/status -Headers @{"X-API-Key" = $KEY}).Content | python -m json.tool
```

---

## Ендпоінти

### GET /status

```bash
curl -s -H "X-API-Key: $KEY" http://localhost:8001/status | python -m json.tool
```

**Очікувана відповідь:**
```json
{
  "vehicle_id_hint": "vehicle-dev",
  "software_version": "0.1.0",
  "uptime_sec": 5,
  "collector_running": false,
  "agent_running": false,
  "db_ok": true,
  "last_measurement_at": "2026-02-22T10:30:00.123Z"
}
```

> `collector_running: false` — норма під час тесту без колектора.
> `db_ok: false` — якщо PostgreSQL недоступний.

---

### GET /channels

```bash
curl -s -H "X-API-Key: $KEY" http://localhost:8001/channels | python -m json.tool
```

**Очікувана відповідь:**
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

> Порожній масив `[]` — якщо в БД немає каналів (виконати `seed_dev.sql`).

---

### GET /data/latest

```bash
curl -s -H "X-API-Key: $KEY" http://localhost:8001/data/latest | python -m json.tool
```

**Очікувана відповідь:**
```json
[
  {"channel_id": 1, "value": 4.72, "time": "2026-02-22T10:30:00.123Z"},
  {"channel_id": 2, "value": null, "time": "2026-02-22T10:30:00.123Z"}
]
```

---

### GET /data

```bash
# Останні 5 хвилин, всі канали
curl -s -H "X-API-Key: $KEY" \
  "http://localhost:8001/data?from=2026-02-22T10:00:00Z&to=2026-02-22T10:05:00Z" \
  | python -m json.tool

# Конкретний канал
curl -s -H "X-API-Key: $KEY" \
  "http://localhost:8001/data?from=2026-02-22T10:00:00Z&to=2026-02-22T10:05:00Z&channel_id=1" \
  | python -m json.tool

# Перевірка truncated (маленький limit)
curl -s -H "X-API-Key: $KEY" \
  "http://localhost:8001/data?from=2026-02-22T10:00:00Z&to=2026-02-22T10:05:00Z&limit=3" \
  | python -m json.tool
```

**Очікувана відповідь:**
```json
{
  "from": "2026-02-22T10:00:00.000Z",
  "to": "2026-02-22T10:05:00.000Z",
  "count": 2,
  "truncated": false,
  "rows": [
    {"channel_id": 1, "value": 4.72, "time": "2026-02-22T10:00:01.000Z"},
    {"channel_id": 2, "value": 3.10, "time": "2026-02-22T10:00:01.000Z"}
  ]
}
```

---

### GET /alarms

```bash
# Всі тривоги за діапазон
curl -s -H "X-API-Key: $KEY" \
  "http://localhost:8001/alarms?from=2026-02-01T00:00:00Z&to=2026-03-01T00:00:00Z" \
  | python -m json.tool

# Тільки активні (не закриті)
curl -s -H "X-API-Key: $KEY" \
  "http://localhost:8001/alarms?from=2026-02-01T00:00:00Z&to=2026-03-01T00:00:00Z&unresolved_only=true" \
  | python -m json.tool
```

**Очікувана відповідь:**
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

---

## Перевірка помилок

### 401 — відсутній ключ

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/status
# → 422  (FastAPI: поле X-API-Key обов'язкове)

curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: wrong_key" http://localhost:8001/status
# → 401
```

### 400 — невалідний діапазон (from >= to)

```bash
curl -s -H "X-API-Key: $KEY" \
  "http://localhost:8001/data?from=2026-02-22T10:05:00Z&to=2026-02-22T10:00:00Z" \
  | python -m json.tool
# → {"error": "invalid_params", "detail": "from must be before to"}
```

### 503 — БД недоступна

Зупинити PostgreSQL → запит до будь-якого ендпоінту (крім `/status`) поверне:
```json
{"detail": "Database unavailable"}
```
`/status` у цьому випадку поверне `200` з `"db_ok": false`.

---

## Перевірка gzip-стиснення

```bash
# Заголовок Content-Encoding: gzip у відповіді на великий /data запит:
curl -s -v -H "X-API-Key: $KEY" \
     -H "Accept-Encoding: gzip" \
     "http://localhost:8001/data?from=2026-02-01T00:00:00Z&to=2026-02-22T00:00:00Z" \
  2>&1 | grep -i "content-encoding"
# → < content-encoding: gzip
```

> `/status` не стискається (`minimum_size=500` — тіло занадто мале).

---

## Швидкий smoke-test (усі ендпоінти разом)

```bash
KEY="dev_outbound_key_change_in_production"
BASE="http://localhost:8001"
H="-H X-API-Key:$KEY"

echo "=== /status ===" && curl -sf $H $BASE/status | python -m json.tool
echo "=== /channels ===" && curl -sf $H $BASE/channels | python -m json.tool
echo "=== /data/latest ===" && curl -sf $H $BASE/data/latest | python -m json.tool
echo "=== /data ===" && curl -sf $H "$BASE/data?from=2026-01-01T00:00:00Z&to=2026-03-01T00:00:00Z&limit=5" | python -m json.tool
echo "=== /alarms ===" && curl -sf $H "$BASE/alarms?from=2026-01-01T00:00:00Z&to=2026-03-01T00:00:00Z" | python -m json.tool
```

---

## Типові проблеми

| Симптом | Причина | Рішення |
|---|---|---|
| `422 Unprocessable Entity` на `/data` | Неправильний формат дати | Використовувати ISO8601 з `Z`: `2026-02-22T10:00:00Z` |
| `[]` у `/channels` та `/data/latest` | Порожня БД | Виконати `db/seed_dev.sql` або запустити колектор |
| `"db_ok": false` у `/status` | PostgreSQL не запущений | `pg_ctl start` або перевірити Docker |
| `"software_version": "unknown"` | Відсутній `version.txt` | Файл є в корені проекту, перевірити шлях |
| `"collector_running": false` | Колектор не запущений | Норма при тесті без `--collector` |
