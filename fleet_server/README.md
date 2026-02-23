# fleet_server

Серверна частина системи телеметрії автопарку (~10 авто).

> Цей репозиторій є частиною  монорепо разом з `auto_telemetry`.
> Спільний контракт синхронізації: [DATA_CONTRACT.md](DATA_CONTRACT.md)

## Стек

| Шар                 | Технологія                                       |              
|---------------------|--------------------------------------------------|
| Web framework       | FastAPI + Jinja2 (серверний рендеринг)           |
| UI                  | AdminLTE v4 (Bootstrap 5)                        |
| Динамічні оновлення | HTMX                                             |
| БД                  | PostgreSQL 16, psycopg2 (sync), RLS              |
| Sync                | asyncio pull-сервіс (httpx)                      |
| Auth                | JWT (access 15хв + refresh 30д, httpOnly cookie) |

## Документація

| Файл | Призначення |
|---|---|
| [DATA_CONTRACT.md](DATA_CONTRACT.md) | Контракт обміну даними між авто та сервером (джерело правди) |
| [docs/SERVER_README.md](docs/SERVER_README.md) | Архітектура, компоненти, вимоги до сервера |
| [docs/STARTUP.md](docs/STARTUP.md) | Запуск локального середовища розробки |
| [docs/Credential.md](docs/Credential.md) | Тестові облікові дані (тільки для локальної розробки) |
| [sync/README.md](sync/README.md)                   | Sync Service: цикл pull, gap-filling, конфігурація, запуск |
| [docs/LOCAL_SYNC_TEST.md](docs/LOCAL_SYNC_TEST.md) | Тестування Sync Service на одному ПК (без VPN) |

## Структура

```
fleet_server/
├── api/                  # FastAPI: auth, REST, WebSocket live
│   ├── main.py
│   ├── auth.py
│   ├── config.py
│   ├── database.py
│   ├── dependencies.py
│   ├── mailer.py
│   ├── routes/
│   │   ├── auth.py
│   │   ├── vehicles.py
│   │   ├── admin.py
│   │   ├── web.py
│   │   └── ws_live.py
│   ├── models/
│   ├── Dockerfile
│   └── requirements.txt
├── sync/                 # Sync Service: pull з авто кожні 30 сек
│   ├── main.py           # asyncio-цикл, паралельний sync всіх авто
│   ├── puller.py         # VehiclePuller — async httpx клієнт
│   ├── writer.py         # DB-операції: batch insert, upsert
│   ├── README.md         # Документація Sync Service
│   ├── Dockerfile
│   └── requirements.txt
├── db/
│   └── 01_init.sql       # Схема PostgreSQL
├── web/
│   └── templates/        # Jinja2 шаблони Web UI
├── nginx/
│   └── nginx.conf
├── docs/                 # Документація
│   ├── SERVER_README.md
│   ├── STARTUP.md
│   └── Credential.md
├── DATA_CONTRACT.md      # Спільний контракт ( корінь монорепо)
├── docker-compose.yml
├── seed_demo.py
├── .env.example
└── .gitignore
```

## Швидкий старт

```bash
cp .env.example .env
# Налаштувати .env

docker compose up -d
```

Детально: [docs/STARTUP.md](docs/STARTUP.md)
