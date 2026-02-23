#!/bin/bash
# Створює роль fleet_app з паролем з env до запуску 01_init.sql
set -e
psql -v ON_ERROR_STOP=1 --username postgres --dbname "$POSTGRES_DB" \
  -c "CREATE ROLE fleet_app WITH LOGIN PASSWORD '$FLEET_APP_PASSWORD';"
