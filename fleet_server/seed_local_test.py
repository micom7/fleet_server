#!/usr/bin/env python3
"""
Seed скрипт для локального тестування Sync Service на одному ПК.

Додає тестове авто з vpn_ip='127.0.0.1' та api_port=8001 — тобто Sync Service
буде тягнути дані з auto_telemetry/outbound, запущеного на тому самому ПК.

Запуск:
    cd f:/fleet_server/fleet_server
    python seed_local_test.py

Потрібно виконати один раз перед запуском sync. При повторному запуску — idempotent.
"""

import psycopg2
import psycopg2.extras

LOCAL_VEHICLE_NAME = "Local Test Vehicle"
LOCAL_VPN_IP       = "127.0.0.1"
LOCAL_PORT         = 8001
# Той самий ключ що OUTBOUND_API_KEY у auto_telemetry/.env
LOCAL_API_KEY      = "dev_outbound_key_change_in_production"


def main() -> None:
    conn = psycopg2.connect(
        host="localhost",
        dbname="fleet",
        user="fleet_app",
        password="devpassword",
    )
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET LOCAL app.user_role = 'superuser'")

            # Перевірити чи авто вже є
            cur.execute(
                "SELECT id, name FROM vehicles WHERE vpn_ip = %s::inet",
                (LOCAL_VPN_IP,),
            )
            row = cur.fetchone()

            if row:
                vehicle_id = row["id"]
                # Оновити ключ та порт на випадок якщо змінились
                cur.execute(
                    "UPDATE vehicles SET name=%s, api_port=%s, api_key=%s WHERE id=%s",
                    (LOCAL_VEHICLE_NAME, LOCAL_PORT, LOCAL_API_KEY, vehicle_id),
                )
                print(f"Авто вже існує, оновлено: {vehicle_id}")
            else:
                cur.execute(
                    "INSERT INTO vehicles (name, vpn_ip, api_port, api_key) "
                    "VALUES (%s, %s::inet, %s, %s) RETURNING id",
                    (LOCAL_VEHICLE_NAME, LOCAL_VPN_IP, LOCAL_PORT, LOCAL_API_KEY),
                )
                vehicle_id = cur.fetchone()["id"]
                print(f"Створено тестове авто: {vehicle_id}")

            print(f"  name    = {LOCAL_VEHICLE_NAME}")
            print(f"  vpn_ip  = {LOCAL_VPN_IP}")
            print(f"  port    = {LOCAL_PORT}")
            print(f"  api_key = {LOCAL_API_KEY}")

        conn.commit()
        print("\nГотово. Тепер запустіть:")
        print("  1. auto_telemetry outbound:  cd auto_telemetry && python -m uvicorn outbound.main:app --port 8001")
        print("  2. fleet_server sync:        cd fleet_server/sync && python main.py")

    except Exception as e:
        conn.rollback()
        print(f"Помилка: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
