# Fleet Server — Запуск

## Вимоги

- Python 3.11+
- PostgreSQL (локально, порт 5432)

---

## 1. Перший запуск (одноразово)

### 1.1. Залежності Python

**PowerShell:**
```powershell
cd F:\fleet_server\fleet_server\api
pip install -r requirements.txt
```

### 1.2. Налаштування .env

Файл `.env` вже є і налаштований для локальної розробки — нічого міняти не потрібно.

### 1.3. База даних

Переконайся що PostgreSQL запущений, потім в PowerShell:

```powershell
# Створити користувача та БД
psql -U postgres -c "CREATE USER fleet_app WITH PASSWORD 'devpassword';"
psql -U postgres -c "CREATE DATABASE fleet OWNER fleet_app;"

# Застосувати схему
psql -U postgres -d fleet -f F:\fleet_server\fleet_server\db\01_init.sql
```

### 1.4. Пароль адміна

Схема створює адміна **без пароля**. Встановити його (запустити один раз):

```powershell
cd F:\fleet_server\fleet_server
python -c "
import bcrypt, psycopg2
h = bcrypt.hashpw(b'Admin123!', bcrypt.gensalt(rounds=12)).decode()
conn = psycopg2.connect(host='localhost', dbname='fleet', user='fleet_app', password='devpassword')
cur = conn.cursor()
cur.execute('UPDATE users SET password_hash = %s WHERE email = %s', (h, 'admin@example.com'))
conn.commit()
conn.close()
print('Пароль встановлено')
"
```

---

## 2. Запуск сервера

Backend і Frontend — **одна команда** (FastAPI роздає і API, і Web UI):

**PowerShell:**
```powershell
cd F:\fleet_server\fleet_server\api
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

**Git Bash:**
```bash
cd /f/fleet_server/fleet_server/api
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Сервер запущений на **http://localhost:8000**

---

## 3. Вхід у Web UI

Відкрий браузер: **http://localhost:8000/login**

| Поле     | Значення              |
|----------|-----------------------|
| Email    | admin@example.com  |
| Password | Admin123!           |

### Основні сторінки

| URL            | Опис                                 |
|----------------|--------------------------------------|
| `/login`       | Сторінка входу / реєстрації          |
| `/fleet`       | Список авто (оновлюється кожні 30с)  |
| `/vehicles/ID` | Деталі авто + live телеметрія        |
| `/admin`       | Панель адміна (users + авто)         |

### REST API документація

| URL       | Опис                |
|-----------|---------------------|
| `/docs`   | Swagger UI          |
| `/redoc`  | ReDoc               |

---

## 4. Зупинка сервера

`Ctrl+C` у терміналі де запущений uvicorn.

Якщо процес завис — в PowerShell:

```powershell
Get-NetTCPConnection -LocalPort 8000 | Select-Object OwningProcess
Stop-Process -Id <PID> -Force
```

---

## Структура проекту

```
fleet_server/
├── api/                    # FastAPI застосунок
│   ├── main.py             # Точка входу
│   ├── config.py           # Налаштування (.env)
│   ├── database.py         # PostgreSQL pool + RLS
│   ├── auth.py             # JWT + bcrypt + Google OAuth
│   ├── dependencies.py     # FastAPI dependencies
│   ├── mailer.py           # Email сповіщення
│   ├── routes/
│   │   ├── auth.py         # /auth/*
│   │   ├── vehicles.py     # /vehicles/*
│   │   ├── admin.py        # /admin/*
│   │   ├── web.py          # Web UI (cookie auth)
│   │   └── ws_live.py      # WebSocket /ws/*
│   ├── models/             # Pydantic моделі
│   └── requirements.txt
├── db/
│   └── 01_init.sql         # Схема PostgreSQL + seed
├── web/
│   └── templates/          # Jinja2 шаблони
│       ├── base.html
│       ├── login.html
│       ├── fleet.html
│       ├── vehicle.html
│       ├── admin.html
│       └── partials/
├── .env                    # Локальні змінні (не в git)
├── .env.example            # Шаблон .env
└── docs/
    ├── SERVER_README.md    # Архітектура
    ├── STARTUP.md          # Цей файл
    └── Credential.md       # Тестові облікові дані
```
