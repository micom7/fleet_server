"""
conftest.py — спільне налаштування для pytest.

Виконується ПЕРЕД імпортом тестових файлів:
- виставляє env-змінні до того як outbound.main їх зчитає
- надає спільні fixtures
"""

import os

# Встановити до імпорту outbound.main (load_dotenv не перезапише вже встановлені)
os.environ['OUTBOUND_API_KEY'] = 'test-key'
os.environ['VEHICLE_ID_HINT'] = 'test-vehicle'

import pytest


@pytest.fixture(autouse=True)
def _patch_api_key(monkeypatch):
    """Гарантує, що outbound.main.API_KEY = 'test-key' у кожному тесті,
    навіть якщо .env завантажив інше значення при першому імпорті."""
    import outbound.main as m
    monkeypatch.setattr(m, 'API_KEY', 'test-key')
