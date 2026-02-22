# Fleet Server — Тестові облікові дані (локальна розробка)

> ⚠️ Тільки для локального середовища. Не використовувати на продакшні.

---

## PostgreSQL

| Параметр | Значення |
|---|---|
| Host | `localhost:5432` |
| Database | `fleet` |
| User | `fleet_app` |
| Password | `devpassword` |

```sql
CREATE USER fleet_app WITH PASSWORD 'devpassword';
CREATE DATABASE fleet OWNER fleet_app;
```

---

## Web UI — адмін

| Поле | Значення |
|---|---|
| URL | http://localhost:8000/login |
| Email | `admin@example.com` |
| Password | `Admin123!` |
| Роль | `superuser` |

---

## Web UI — demo-власник (seed_demo.py)

| Поле | Значення |
|---|---|
| Email | `demo@example.com` |
| Password | *(не встановлено — вхід через адмін-панель)* |
| Роль | `owner` |
| Demo VPN IP | `10.0.0.99` |
| Demo port | `8001` |

---

## Grafana

| Поле | Значення |
|---|---|
| User | `admin` |
| Password | `devpassword` |

---

## JWT (dev)

| Параметр | Значення |
|---|---|
| JWT_SECRET | `dev_jwt_secret_not_for_production_use_only` |
| Access token TTL | 15 хв |
| Refresh token TTL | 30 днів |

---

## Sync Service / Outbound API

| Параметр | Значення |
|---|---|
| VEHICLE_DEFAULT_API_KEY | *(не встановлено — задати при підключенні реального авто)* |
| Порт Outbound API на авто | `8001` |
| Інтервал sync | 30 сек |
