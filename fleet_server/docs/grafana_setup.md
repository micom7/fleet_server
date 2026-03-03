# Grafana — налаштування та доступ

## Доступ

### Через SSH тунель (адмін-доступ)
```powershell
ssh -i C:\Users\Dell\.ssh\id_ed25519 -L 3001:localhost:3000 -N root@89.167.89.108
```
Потім відкрити: `http://localhost:3001`

- User: `admin`
- Password: `Admin123!`

### Через портал (звичайні користувачі)
URL: `https://autotelemetry.duckdns.org/grafana/`

Grafana використовує Auth Proxy (`GF_AUTH_PROXY_ENABLED=true`) — користувач автоматично логіниться через заголовок `X-WEBAUTH-USER`, який прокидає nginx після авторизації в Fleet порталі. Тому через браузер напряму адмін-логін недоступний — тільки через тунель.

---

## Мережева конфігурація

Для доступу Grafana до telemetry БД обидва контейнери підключені до `telemetry_net`:

| Контейнер | Мережі |
|---|---|
| `fleet_server-grafana-1` | `fleet_server_default`, `telemetry_net` |
| `auto_telemetry-postgres-1` | `auto_telemetry_default`, `telemetry_net` |

Зміни у compose файлах:
- [fleet_server/docker-compose.yml](../docker-compose.yml) — додано `telemetry_net` до grafana сервісу
- [auto_telemetry/docker-compose.yml](../../auto_telemetry/docker-compose.yml) — додано `telemetry_net` до postgres сервісу

Підключення зроблено і динамічно (без перезапуску):
```bash
docker network connect telemetry_net fleet_server-grafana-1
docker network connect telemetry_net auto_telemetry-postgres-1
```

---

## Datasource

| Параметр | Значення |
|---|---|
| Name | `TelemetryDB` |
| Type | PostgreSQL |
| Host | `auto_telemetry-postgres-1:5432` |
| Database | `telemetry` |
| User | `telemetry` |
| Password | `telemetry123` |
| SSL | disabled |
| UID | `afevpz7mi5dz4b` |

---

## Дашборд "Vehicle Multi-Metric"

- UID: `vehicle-multi`
- URL: `/d/vehicle-multi/vehicle-multi-metric`

### Структура telemetry БД

**Таблиця `measurements`:** `time`, `channel_id`, `value`

**Таблиця `channel_config`:** `channel_id`, `module`, `name`, `unit`, ...

Канали (18 штук):
| channel_id | module | name | unit |
|---|---|---|---|
| 1 | et7017_1 | Temp Engine | C |
| 2 | et7017_1 | Temp Gearbox | C |
| 3 | et7017_1 | Oil Pressure | bar |
| 4 | et7017_1 | Fuel Pressure | bar |
| 5 | et7017_1 | Coolant Level | % |
| 6 | et7017_1 | Fuel Level | % |
| 7 | et7017_1 | Battery | V |
| 8 | et7017_1 | RPM Engine | rpm |
| 9 | et7017_2 | Vibration X | mm/s |
| 10 | et7017_2 | Vibration Y | mm/s |
| 11 | et7017_2 | Vibration Gear | mm/s |
| 12 | et7017_2 | Hydraulic P | bar |
| 13 | et7017_2 | Hydraulic Temp | C |
| 14 | et7017_2 | Flow Rate | L/min |
| 15 | et7017_2 | Load Cell 1 | t |
| 16 | et7017_2 | Load Cell 2 | t |
| 17 | et7284 | Position | m |
| 18 | et7284 | Speed | km/h |

### Variable `channel`
- Тип: Query, multi-value, include All
- Query:
```sql
SELECT channel_id::text AS __value,
       name || ' (' || COALESCE(unit,'') || ')' AS __text
FROM channel_config
WHERE enabled = true
ORDER BY channel_id
```

### SQL запит панелі
```sql
SELECT
  m.time AS "time",
  cc.name || ' (' || COALESCE(cc.unit,'') || ')' AS metric,
  m.value
FROM measurements m
JOIN channel_config cc ON cc.channel_id = m.channel_id
WHERE m.channel_id IN ($channel)
  AND $__timeFilter(m.time)
ORDER BY m.time
```
