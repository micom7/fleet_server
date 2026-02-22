# Auto Telemetry — Серверна частина (Fleet Server)

Центральний сервер для збору, зберігання та відображення телеметрії з автопарку.

> Контракт обміну даними між машинами та сервером: **DATA_CONTRACT.md**

## Розміщення

- **VPS** (Hetzner CX32 або аналог): 4 vCPU, 8 GB RAM, 80 GB SSD + окремий Volume ~300 GB
- **Домен:** `fleet.example.com` (субдомен, A-запис → IP сервера; основний сайт не чіпається)
- **SSL:** Let's Encrypt (безкоштовно)

## Архітектура

```
[Авто 1..N: RUTX11 + Outbound API :8001]
        ↕ WireGuard VPN (10.0.0.x)
         ┌──────────────────────┐
         │      Fleet Server    │
         │                      │
         │   Sync Service       │  ← pull кожні 30 сек
         │       ↓              │
         │   PostgreSQL         │  ← центральна БД (RLS)
         │       ↓              │
         │   FastAPI            │  ← auth + REST + WebSocket
         │       ↓              │
         │   Grafana            │  ← графіки (auth proxy)
         │       ↓              │
         │   Web UI (браузер)   │
         └──────────────────────┘
```

## Компоненти

### WireGuard VPN
- Сервер на VPS, кожне авто (RUTX11) — окремий клієнт з фіксованим IP
- `10.0.0.1` — сервер, `10.0.0.11..20` — авто
- Sync Service та WebSocket live звертаються до авто за VPN IP

### Sync Service
- Python asyncio сервіс, опитує всі авто **паралельно** кожні 30 сек
- Pull через Outbound API авто (порт **8001**): `/status`, `/channels`, `/data`, `/alarms`
- Логіка pull-вікна: `from = vehicles.last_sync_at ?? (now - 60s)`, `to = now`
- При `truncated=true` — розбиває на 10-хвилинні вікна
- При gap > 24 год — розбиває на 1-годинні вікна
- Записує в центральну БД batch-інсертом з дедублікацією (`ON CONFLICT DO NOTHING`)
- Зберігає `last_sync_at` — при розриві тягне gap при наступному підключенні
- Логує кожен цикл у `sync_journal` (статус: ok / timeout / error)

### PostgreSQL (центральна БД)
Мультитенантна схема з **Row Level Security**. Ключові таблиці:

| Таблиця | Призначення |
|---|---|
| `users` | Акаунти (superuser / owner), статус (pending / active / blocked) |
| `oauth_accounts` | Прив'язка Google акаунтів |
| `revoked_tokens` | Анульовані JWT при блокуванні |
| `vehicles` | Авто: VPN IP, порт (8001), api_key, last_seen_at, last_sync_at, sync_status, software_version |
| `vehicle_access` | Many-to-many: user ↔ vehicle |
| `channel_config` | Конфігурація каналів (копія з авто, оновлюється при sync) |
| `measurements` | Вимірювання з `vehicle_id`, партиціювання по місяцях |
| `alarms_log` | Тривоги з авто (alarm_id — BIGINT) |
| `sync_journal` | Історія синхронізацій (30 днів) |

RLS реалізована через `set_config('app.user_id')` + `set_config('app.user_role')` перед кожним запитом — власник фізично не може отримати дані чужого авто навіть при баг в API.

Партиціювання `measurements` по місяцях → видалення старих даних через `DROP TABLE` без bloat.

### FastAPI (Auth + API)
**Аутентифікація:**
- Логін + пароль (bcrypt, cost 12)
- Google OAuth
- JWT: access token (15 хв) + refresh token (30 днів, httpOnly cookie)
- Rate limiting на `/auth/login` — 5 спроб/хв з IP

**Реєстрація власника:**
1. Власник реєструється (email+пароль або Google) → статус `pending`
2. Superuser отримує сповіщення → підтверджує → `active` + призначає авто
3. Власник отримує email "акаунт активовано"
4. До підтвердження: вхід дозволений, але бачить лише "очікує підтвердження"

**Ключові endpoints:**
```
POST /auth/register
POST /auth/login
GET  /auth/google + /auth/google/callback

GET  /vehicles                        → список авто (фільтровано по ролі)
GET  /vehicles/{id}/status            → online/offline, last_seen_at
GET  /vehicles/{id}/alarms            → активні тривоги

WS   /ws/vehicles/{id}/live           → WebSocket live-потік

GET  /admin/users/pending             → superuser: очікують підтвердження
POST /admin/users/{id}/approve
POST /admin/users/{id}/reject
POST /admin/users/{id}/block
POST /admin/vehicles/{id}/assign      → прив'язати авто до власника
```

### WebSocket Live
Власник може відкрити live-перегляд авто з затримкою ~2-3 сек:
- Браузер підключається до `wss://fleet.example.com/ws/vehicles/{id}/live?token=...`
- Сервер кожні 2 сек робить `GET /data/latest` до конкретного авто (Outbound API :8001)
- При недоступності авто: WebSocket залишається відкритим, браузер показує "offline"
- Sync Service при цьому продовжує працювати незалежно

### Grafana
- Одна Grafana на сервері, мультитенантна через Auth Proxy
- FastAPI передає ідентичність користувача через заголовок
- Дашборд має змінну `$vehicle_id` — значення обмежені тільки авто поточного користувача
- Для superuser: всі авто; для owner: тільки свої

### Web UI
Три секції:
- **Флот** — список авто зі статусом online/offline, остання активність
- **Авто** — поточні значення (WebSocket live), вбудована Grafana (iframe), активні тривоги, кнопка "Live"
- **Адмін** (тільки superuser) — управління користувачами, підтвердження реєстрацій, прив'язка авто

## Ролі та права

| Дія | superuser | owner |
|---|---|---|
| Бачити всі авто | ✓ | — |
| Бачити свої авто | ✓ | ✓ |
| Live-перегляд | ✓ | ✓ (тільки свої) |
| Grafana графіки | ✓ (всі) | ✓ (тільки свої) |
| Тривоги | ✓ (всі) | ✓ (тільки свої) |
| Підтверджувати акаунти | ✓ | — |
| Призначати авто | ✓ | — |
| Блокувати користувачів | ✓ | — |

## Вимоги до сервера

| Ресурс | Мінімум | Рекомендовано |
|---|---|---|
| vCPU | 2 | 4 |
| RAM | 4 GB | 8 GB |
| SSD (ОС + сервіси) | 40 GB | 80 GB |
| Volume (дані) | 100 GB | 300 GB |
| Мережа | 10 Mbps | 100 Mbps |

**Навантаження:** 10 авто × 25 каналів × 1 Гц = 250 рядків/сек → ~1 GB/добу на авто → ~10 GB/добу всього.

## Безпека

### ⚠️ Docker та файрвол — критична пастка

Docker керує iptables **напряму** і обходить ufw/firewalld. Це означає що порт пробрешений як `"8000:8000"` буде видний на весь інтернет — навіть якщо файрвол закритий.

**Неправильно** — порт доступний з будь-якого IP:
```yaml
ports:
  - "8000:8000"    # ← світиться на весь інтернет
  - "5432:5432"    # ← БД відкрита назовні!
```

**Правильно** — порт доступний тільки локально:
```yaml
ports:
  - "127.0.0.1:8000:8000"    # ← тільки localhost
  - "127.0.0.1:5432:5432"    # ← БД недоступна зовні
```

**Правило для флот-сервера:**

| Сервіс | Binding | Причина |
|---|---|---|
| nginx | `0.0.0.0:80/443` | єдина публічна точка входу |
| FastAPI | `127.0.0.1:8000` | за nginx proxy |
| PostgreSQL | `127.0.0.1:5432` | тільки для сервісів на сервері |
| Grafana | `127.0.0.1:3000` | за nginx proxy |
| Sync Service | без портів | тільки вихідні з'єднання до авто |

Назовні відкритий **тільки nginx** (80/443) та **WireGuard** (UDP, окремий порт). Все інше — тільки `127.0.0.1`.

---

## Бекап

Щоденний pg_dump на Hetzner Object Storage (або S3-сумісне сховище).
При ~250 GB БД: dump ~50-80 GB після стиснення, час ~кілька хвилин.

## Структура проекту (сервер)

```
fleet_server/
├── sync/            # Sync Service (pull з авто → центральна БД)
│   ├── main.py
│   ├── puller.py
│   ├── writer.py
│   └── settings.py
├── api/             # FastAPI (auth, REST, WebSocket)
│   ├── main.py
│   ├── auth.py
│   ├── routes/
│   │   ├── auth.py
│   │   ├── vehicles.py
│   │   ├── admin.py
│   │   ├── web.py
│   │   └── ws_live.py
│   └── models/
│       ├── vehicle.py   # VehicleCreate.api_port default = 8001
│       └── user.py
├── db/
│   └── 01_init.sql      # Схема центральної БД
├── grafana/         # Provisioning, auth proxy config
├── web/             # Web UI (Jinja2 шаблони)
│   └── templates/
├── nginx/
│   └── nginx.conf
├── docker-compose.yml
├── .env.example
└── DATA_CONTRACT.md     # Контракт синхронізації (джерело правди)
```

## Етапи реалізації

| # | Етап | Опис |
|---|---|---|
| 1 | Інфраструктура | WireGuard на VPS, конфіги для RUTX11, nginx + SSL |
| 2 | Центральна БД | Схема з vehicle_id, RLS, партиції measurements |
| 3 | Outbound API на авто | `/status`, `/data`, `/data/latest`, `/alarms`, `/channels` (порт 8001) |
| 4 | Sync Service | Pull-сервіс, gap-filling, sync_journal, статуси авто |
| 5 | FastAPI Auth + API | JWT, Google OAuth, реєстрація з підтвердженням |
| 6 | WebSocket Live | On-demand pull кожні 2 сек для live-перегляду |
| 7 | Grafana | Auth proxy, мультитенантні дашборди |
| 8 | Web UI | Флот, сторінка авто, адмін-панель |
