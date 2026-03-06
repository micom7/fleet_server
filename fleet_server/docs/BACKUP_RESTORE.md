# Backup & Restore

## Що бекапити

| Що | Де | Розмір (зараз) |
|----|----|----------------|
| БД `fleet` (вимірювання, юзери, авто) | Docker volume `fleet_server_postgres_data` | ~876 MB |
| Grafana dashboards/datasources | Docker volume `fleet_server_grafana_data` | мало |
| Конфіг сервера | `/opt/fleet_server/fleet_server/` | мало |

SSL-сертифікати (`/etc/letsencrypt/`) автоматично поновлюються certbot — бекапити не обов'язково.

---

## Backup БД (рекомендований спосіб)

`pg_dump` дає стиснутий SQL-дамп без зупинки сервісів.

```bash
# На сервері — створити дамп
docker exec fleet_server-postgres-1 \
  pg_dump -U postgres -Fc fleet \
  > /opt/backups/fleet_$(date +%Y%m%d_%H%M).dump

# Перевірити що файл не порожній
ls -lh /opt/backups/
```

Завантажити локально:
```bash
# На локальній машині (Windows Git Bash)
scp -i ~/.ssh/id_ed25519 \
  root@89.167.89.108:/opt/backups/fleet_*.dump \
  ./backups/
```

---

## Backup конфігурації

```bash
# На сервері
tar -czf /opt/backups/fleet_config_$(date +%Y%m%d).tar.gz \
  /opt/fleet_server/fleet_server/.env \
  /opt/fleet_server/auto_telemetry/.env \
  /etc/letsencrypt/live/autotelemetry.duckdns.org/
```

---

## Автоматичний щотижневий backup (cron)

```bash
# На сервері — відкрити crontab
crontab -e
```

Додати рядок (щонеділі о 03:00):
```
0 3 * * 0 mkdir -p /opt/backups && docker exec fleet_server-postgres-1 pg_dump -U postgres -Fc fleet > /opt/backups/fleet_$(date +\%Y\%m\%d).dump && find /opt/backups -name "fleet_*.dump" -mtime +30 -delete
```

Команда: створює дамп + видаляє дампи старше 30 днів.

---

## Restore БД

**Увага:** restore повністю замінює поточну БД.

```bash
# 1. Зупинити API і sync (щоб не було активних з'єднань)
cd /opt/fleet_server/fleet_server
docker compose stop api sync

# 2. Відновити з дампу
docker exec -i fleet_server-postgres-1 \
  pg_restore -U postgres -d fleet --clean --if-exists \
  < /opt/backups/fleet_20260301_0300.dump

# 3. Запустити назад
docker compose start api sync

# 4. Перевірити
curl https://autotelemetry.duckdns.org/health
```

---

## Перенос на новий сервер

```bash
# 1. На старому сервері — зробити дамп + скопіювати конфіг
docker exec fleet_server-postgres-1 pg_dump -U postgres -Fc fleet > /tmp/fleet.dump
tar -czf /tmp/fleet_config.tar.gz /opt/fleet_server/

# 2. Перенести файли на новий сервер
scp root@OLD_IP:/tmp/fleet.dump root@NEW_IP:/tmp/
scp root@OLD_IP:/tmp/fleet_config.tar.gz root@NEW_IP:/tmp/

# 3. На новому сервері — розгорнути
cd /opt && tar -xzf /tmp/fleet_config.tar.gz
cd /opt/fleet_server/fleet_server
docker compose up -d postgres
sleep 10

# 4. Restore БД (схема вже ініціалізована через 01_init.sql при першому старті)
# Але при restore з --clean вона буде перезаписана
docker exec -i fleet_server-postgres-1 \
  pg_restore -U postgres -d fleet --clean --if-exists < /tmp/fleet.dump

# 5. Запустити всі сервіси
docker compose up -d
```

---

## Перевірка цілісності дампу

```bash
# Список таблиць і кількість рядків після restore
docker exec fleet_server-postgres-1 psql -U postgres -d fleet -c "
  SELECT schemaname, tablename,
         pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
  FROM pg_tables
  WHERE schemaname = 'public'
  ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
"
```
