#!/usr/bin/env python3
"""
Seed script: створює демо-користувача, демо-авто та прив'язку між ними.

Запускати один раз після початкового налаштування БД.

Використання:
    cd F:\\fleet_server
    python seed_demo.py
"""

import psycopg2
import psycopg2.extras

DEMO_EMAIL = "demo@example.com"
DEMO_NAME  = "Demo User"
DEMO_VPN   = "10.0.0.99"
DEMO_PORT  = 8080


def main():
    conn = psycopg2.connect(
        host="localhost",
        dbname="fleet",
        user="fleet_app",
        password="devpassword",
    )
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            # Demo user
            cur.execute("SELECT id FROM users WHERE email = %s", (DEMO_EMAIL,))
            row = cur.fetchone()
            if row:
                user_id = row["id"]
                print(f"Demo user вже існує: {user_id}")
            else:
                cur.execute(
                    "INSERT INTO users (email, role, status, full_name) "
                    "VALUES (%s, 'owner', 'active', %s) RETURNING id",
                    (DEMO_EMAIL, DEMO_NAME),
                )
                user_id = cur.fetchone()["id"]
                print(f"Створено demo user: {user_id}")

            # Demo vehicle
            cur.execute(
                "SELECT id FROM vehicles WHERE vpn_ip = %s::inet", (DEMO_VPN,)
            )
            row = cur.fetchone()
            if row:
                vehicle_id = row["id"]
                print(f"Demo vehicle вже існує: {vehicle_id}")
            else:
                cur.execute(
                    "INSERT INTO vehicles (name, vpn_ip, api_port) "
                    "VALUES ('Demo Vehicle', %s::inet, %s) RETURNING id",
                    (DEMO_VPN, DEMO_PORT),
                )
                vehicle_id = cur.fetchone()["id"]
                print(f"Створено demo vehicle: {vehicle_id}")

            # Access assignment
            cur.execute(
                "INSERT INTO vehicle_access (user_id, vehicle_id) "
                "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, vehicle_id),
            )
            print("Доступ призначено.")

        conn.commit()
        print("Готово. Demo-вхід доступний на /demo")

    except Exception as e:
        conn.rollback()
        print(f"Помилка: {e}")
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()
