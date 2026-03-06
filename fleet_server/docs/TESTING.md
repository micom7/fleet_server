# Порядок тестування

## Передумови

1. Запущений PostgreSQL з ініціалізованою БД `fleet` (через `docker compose up postgres`)
2. Файл `fleet_server/.env` заповнено (мінімум `DB_PASSWORD` і `JWT_SECRET`)
3. Python-залежності встановлено

```bash
# З директорії fleet_server/
pip install -r api/requirements.txt
pip install -r tests/requirements-test.txt
```

---

## Запуск тестів

```bash
# З директорії fleet_server/
pytest tests/ -v
```

Очікуваний вивід:
```
tests/test_auth.py::test_login_success                          PASSED
tests/test_auth.py::test_login_wrong_password                   PASSED
tests/test_auth.py::test_login_unknown_email                    PASSED
tests/test_auth.py::test_login_blocked_user                     PASSED
tests/test_auth.py::test_pending_user_cannot_access_vehicles    PASSED
tests/test_auth.py::test_active_user_can_access_vehicles        PASSED
tests/test_auth.py::test_no_token_returns_401                   PASSED
tests/test_auth.py::test_refresh_returns_new_access_token       PASSED
tests/test_auth.py::test_refresh_without_cookie_returns_401     PASSED
tests/test_auth.py::test_logout_revokes_refresh_token           PASSED
tests/test_auth.py::test_me_returns_current_user                PASSED
tests/test_rls.py::test_owner_sees_only_own_vehicle             PASSED
tests/test_rls.py::test_owner_cannot_access_other_vehicle_by_id PASSED
tests/test_rls.py::test_superuser_sees_all_vehicles             PASSED
tests/test_rls.py::test_owner_without_any_vehicle_sees_empty_list PASSED
tests/test_sync.py::test_write_measurements_inserts_rows        PASSED
tests/test_sync.py::test_write_measurements_deduplication       PASSED
tests/test_sync.py::test_write_measurements_skips_null_values   PASSED
tests/test_sync.py::test_upsert_channels_creates_and_updates    PASSED
tests/test_sync.py::test_update_vehicle_seen_sets_sync_status_ok PASSED
tests/test_sync.py::test_update_last_sync_at                    PASSED
tests/test_sync.py::test_write_journal_records_cycle            PASSED
```

---

## Що тестується

### T1 — Auth (`test_auth.py`)

| Тест | Перевірка |
|------|-----------|
| login_success | 200 + access_token |
| login_wrong_password | 401 |
| login_unknown_email | 401 |
| login_blocked_user | 403 |
| pending_user_cannot_access_vehicles | 403 на `/api/vehicles` |
| active_user_can_access_vehicles | 200 |
| no_token_returns_401 | 401 без заголовка Authorization |
| refresh_returns_new_access_token | refresh cookie → новий access_token |
| refresh_without_cookie_returns_401 | 401 без cookie |
| logout_revokes_refresh_token | після logout refresh повертає 401 |
| me_returns_current_user | правильний email/role/status |

### T2 — RLS (`test_rls.py`)

| Тест | Перевірка |
|------|-----------|
| owner_sees_only_own_vehicle | в списку тільки призначені авто |
| owner_cannot_access_other_vehicle_by_id | 404 на чуже авто (RLS фільтрує) |
| superuser_sees_all_vehicles | superuser бачить всі авто |
| owner_without_any_vehicle_sees_empty_list | порожній список, не помилка |

### T3 — Sync writer (`test_sync.py`)

| Тест | Перевірка |
|------|-----------|
| write_measurements_inserts_rows | 2 рядки записуються в БД |
| write_measurements_deduplication | ON CONFLICT DO NOTHING (той самий timestamp) |
| write_measurements_skips_null_values | value=null пропускається |
| upsert_channels_creates_and_updates | INSERT + UPDATE назви каналу |
| update_vehicle_seen_sets_sync_status_ok | sync_status='ok', software_version оновлено |
| update_last_sync_at | last_sync_at зберігається коректно |
| write_journal_records_cycle | запис у sync_journal з правильними полями |

---

## Ізоляція тестів

- Кожен тест створює тест-дані з унікальними ідентифікаторами (UUID-based email, IP 10.99.0.x)
- Cleanup відбувається в `pytest` fixture teardown — навіть якщо тест впав
- Тести не залежать від наявності SimAuto або будь-якого авто в БД

## Ручне тестування після деплою

Після `docker compose up -d --build api` виконати:

```bash
# Health check
curl https://autotelemetry.duckdns.org/health

# Login
curl -c /tmp/cookies.txt -X POST https://autotelemetry.duckdns.org/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"Admin123!"}'

# Список авто (підставити токен з попереднього кроку)
curl -H "Authorization: Bearer <TOKEN>" https://autotelemetry.duckdns.org/api/vehicles
```
