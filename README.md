# Fleet Server

Центральний сервер для збору та відображення телеметрії з автопарку.

→ Архітектура та проектні рішення: SERVER_README.md

## Структура

```
fleet_server/
├── api/                  # FastAPI: auth, REST, WebSocket live
│   ├── main.py           # точка входу
│   ├── auth.py           # JWT + Google OAuth
│   ├── routes/           # endpoints по модулях
│   │   ├── vehicles.py
│   │   ├── admin.py
│   │   └── ws_live.py
│   ├── models/           # Pydantic схеми
│   ├── Dockerfile
│   └── requirements.txt
├── sync/                 # Sync Service: pull даних з авто
│   ├── main.py
│   ├── puller.py
│   ├── writer.py
│   ├── settings.py
│   ├── Dockerfile
│   └── requirements.txt
├── db/
│   └── 01_init.sql       # схема центральної БД
├── grafana/
│   └── provisioning/     # datasources, dashboards
├── nginx/
│   └── nginx.conf        # reverse proxy + SSL
├── web/                  # Web UI (шаблони)
│   └── templates/
├── docker-compose.yml
├── .env.example          # скопіювати в .env та заповнити
└── .gitignore
```

## Швидкий старт

### 1. Клонувати та налаштувати
```bash
git clone ...
cd fleet_server
cp .env.example .env
# Відредагувати .env — замінити всі ЗМІНИТИ_НА_ПРОДАКШН
```

### 2. SSL сертифікат (Let's Encrypt)
```bash
# Встановити certbot
apt install certbot
certbot certonly --standalone -d fleet.example.com

# Скопіювати сертифікати
cp /etc/letsencrypt/live/fleet.example.com/fullchain.pem nginx/certs/
cp /etc/letsencrypt/live/fleet.example.com/privkey.pem   nginx/certs/
```

### 3. Ініціалізація БД
```bash
docker compose up postgres -d
docker compose exec postgres psql -U fleet_app -d fleet -f /docker-entrypoint-initdb.d/01_init.sql
```

### 4. Запустити всі сервіси
```bash
docker compose up -d
```

### Перевірка
- API: https://fleet.example.com/docs
- Grafana: https://fleet.example.com/grafana
- Статус сервісів: `docker compose ps`
- Логи sync: `docker compose logs -f sync`

## Безпека — важливо

Всі сервіси крім nginx прив'язані до `127.0.0.1`:

```yaml
# ПРАВИЛЬНО
ports:
  - "127.0.0.1:8000:8000"

# НЕПРАВИЛЬНО — порт видний на весь інтернет навіть з файрволом
ports:
  - "8000:8000"
```

Docker обходить ufw/firewalld через iptables напряму.
Назовні відкриті тільки: **nginx** (80/443) + **WireGuard** (51820/udp).

## WireGuard VPN

```
Сервер: 10.0.0.1
Авто 1: 10.0.0.11
Авто 2: 10.0.0.12
...
Авто N: 10.0.0.1N
```

Конфігурація: `/etc/wireguard/wg0.conf` на VPS (поза Docker).

## Етапи реалізації

- [ ] Етап 1 — WireGuard + nginx + SSL
- [ ] Етап 2 — Схема БД (`db/01_init.sql`)
- [ ] Етап 3 — Outbound API на авто (`/data/latest`, `/alarms`, `/channels`)
- [ ] Етап 4 — Sync Service
- [ ] Етап 5 — FastAPI Auth (реєстрація, JWT, Google OAuth)
- [ ] Етап 6 — FastAPI API (vehicles, alarms, WebSocket live)
- [ ] Етап 7 — Grafana (auth proxy, дашборди)
- [ ] Етап 8 — Web UI
