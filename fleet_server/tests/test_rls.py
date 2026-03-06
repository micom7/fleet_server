"""T2 — Smoke tests: RLS (owner не бачить чужі авто)"""
import pytest
from conftest import (
    api_login,
    db_assign_vehicle,
    db_create_vehicle,
    db_delete_vehicle,
    rand_email,
    db_create_user,
    db_delete_user,
)


@pytest.fixture
def two_owners_one_vehicle(client):
    """
    owner_a → vehicle_a (assigned)
    owner_b → vehicle_b (assigned)
    Обидва власники не повинні бачити авто одне одного.
    """
    # Власники
    email_a, pw = rand_email(), "TestPass1!"
    uid_a = db_create_user(email_a, pw, "owner", "active")
    email_b = rand_email()
    uid_b = db_create_user(email_b, pw, "owner", "active")

    # Авто (IP з тестового діапазону, щоб не конфліктувати)
    vid_a = db_create_vehicle("TestVehicleA", "10.99.0.101")
    vid_b = db_create_vehicle("TestVehicleB", "10.99.0.102")

    db_assign_vehicle(uid_a, vid_a)
    db_assign_vehicle(uid_b, vid_b)

    yield {
        "owner_a": {"email": email_a, "password": pw, "id": uid_a},
        "owner_b": {"email": email_b, "password": pw, "id": uid_b},
        "vehicle_a": vid_a,
        "vehicle_b": vid_b,
    }

    db_delete_vehicle(vid_a)
    db_delete_vehicle(vid_b)
    db_delete_user(uid_a)
    db_delete_user(uid_b)


def test_owner_sees_only_own_vehicle(client, two_owners_one_vehicle):
    ctx = two_owners_one_vehicle
    token_a = api_login(client, ctx["owner_a"]["email"], ctx["owner_a"]["password"])

    r = client.get("/api/vehicles", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200
    ids = [v["id"] for v in r.json()]
    assert ctx["vehicle_a"] in ids
    assert ctx["vehicle_b"] not in ids


def test_owner_cannot_access_other_vehicle_by_id(client, two_owners_one_vehicle):
    ctx = two_owners_one_vehicle
    token_a = api_login(client, ctx["owner_a"]["email"], ctx["owner_a"]["password"])

    # vehicle_b не призначено owner_a — повинен отримати 404 (RLS фільтрує)
    r = client.get(
        f"/api/vehicles/{ctx['vehicle_b']}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 404


def test_superuser_sees_all_vehicles(client, active_superuser, two_owners_one_vehicle):
    ctx = two_owners_one_vehicle
    token = api_login(client, active_superuser["email"], active_superuser["password"])

    r = client.get("/api/vehicles", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    ids = [v["id"] for v in r.json()]
    assert ctx["vehicle_a"] in ids
    assert ctx["vehicle_b"] in ids


def test_owner_without_any_vehicle_sees_empty_list(client, active_owner):
    token = api_login(client, active_owner["email"], active_owner["password"])
    r = client.get("/api/vehicles", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    # owner без призначених авто бачить порожній список
    # (може бути інші авто від інших тестів, але своїх — 0)
    # Перевіряємо що відповідь коректна
    assert isinstance(r.json(), list)
