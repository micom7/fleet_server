# Довготривале тестування — SimAuto на Hetzner

## Сервер
- **IP**: `89.167.89.108`
- **Домен**: `autotelemetry.duckdns.org`
- **SSH**: `ssh -i /c/Users/ogagi/.ssh/id_ed25519 root@89.167.89.108`

## Fleet Server (Docker)
- **Директорія**: `/opt/fleet_server/fleet_server/`
- **URL**: `https://autotelemetry.duckdns.org`
- **Grafana**: `https://autotelemetry.duckdns.org/grafana`
- **Admin**: `admin@example.com` / `Admin123!`
- **DB user**: `fleet_app`, DB: `fleet`
- **Важливо**: `DB_HOST=postgres` у `.env` (не localhost!)

```bash
# Логи sync
cd /opt/fleet_server/fleet_server
docker compose logs -f sync

# Перезапуск
docker compose restart sync
```

## Auto Telemetry Simulator (Docker)
- **Директорія**: `/opt/fleet_server/auto_telemetry/`
- **3 контейнери**: `postgres`, `simulator`, `outbound`
- **Telemetry DB**: порт `127.0.0.1:5433` на хості (всередині: 5432)
- **DB user**: `telemetry` / пароль з `.env`
- **Outbound API**: `http://10.200.0.50:8001` (тільки всередині Docker)
- **API key**: `strong_api_key`

```bash
# Логи
cd /opt/fleet_server/auto_telemetry
docker compose logs -f simulator
docker compose logs -f outbound

# Статус
docker compose ps
```

## Зареєстроване авто SimAuto
| Поле | Значення |
|------|----------|
| name | SimAuto |
| vpn_ip | 10.200.0.50 |
| api_port | 8001 |
| api_key | strong_api_key |

Оновити api_key через БД (якщо змінено):
```bash
cd /opt/fleet_server/fleet_server
docker compose exec postgres psql -U fleet_app -d fleet -c \
  "UPDATE vehicles SET api_key='strong_api_key' WHERE name='SimAuto';"
```

## Docker мережа
- **Назва**: `telemetry_net`
- **Підмережа**: `10.200.0.0/24`
- **Outbound IP**: `10.200.0.50` (фіксований)
- **Sync IP**: `10.200.0.2` (автоматичний)
- Спільна між двома compose-проєктами

```bash
docker network inspect telemetry_net
```

## Що генерується
- 18 каналів (температури, тиски, вібрація, рівні, RPM, позиція, швидкість)
- Інтервал запису: 2 секунди → ~540 рядків/хв
- Sync тягне дані кожні 30 секунд
- Тривоги: 6 правил (engine overtemp, low oil pressure, low fuel, low battery, hydraulic overP)

## Деплой оновлень

З локальної машини (Git Bash, з `/f/fleet_server`):
```bash
# Оновити fleet_server
scp -i /c/Users/ogagi/.ssh/id_ed25519 -r \
  fleet_server/. root@89.167.89.108:/opt/fleet_server/fleet_server/

# Оновити auto_telemetry
scp -i /c/Users/ogagi/.ssh/id_ed25519 -r \
  auto_telemetry/. root@89.167.89.108:/opt/fleet_server/auto_telemetry/
```

На сервері після оновлення коду:
```bash
cd /opt/fleet_server/fleet_server && docker compose up -d --build
cd /opt/fleet_server/auto_telemetry && docker compose up -d --build
```

## Відомі нюанси
- `rsync` не встановлений на Windows Git Bash → використовувати `scp -r`
- `POSTGRES_USER=postgres` не існує у fleet DB → використовувати `fleet_app`
- Статичний IP `10.200.0.2` зайнятий sync → outbound отримав `10.200.0.50`
- `DB_HOST` у fleet_server `.env` був `localhost` → виправлено на `postgres`
