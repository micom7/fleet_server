"""
Запуск порталу як десктопного вікна.

Стартує FastAPI сервер у фоновому потоці,
потім відкриває pywebview вікно.

Запуск: python run_portal.py
"""

import threading
import time
import urllib.request
import urllib.error

import uvicorn
import webview

from portal.main import app


def start_server() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8100, log_level="warning")


def wait_for_server(url: str, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    return False


if __name__ == "__main__":
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    if not wait_for_server("http://127.0.0.1:8100"):
        print("Помилка: сервер не запустився")
        raise SystemExit(1)

    window = webview.create_window(
        title="Telemetry Portal",
        url="http://127.0.0.1:8100",
        width=1280,
        height=800,
        min_size=(800, 500),
    )
    webview.start()
