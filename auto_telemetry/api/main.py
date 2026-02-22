"""
FastAPI: експорт даних (CSV), керування та статус системи.
"""

from fastapi import FastAPI

app = FastAPI(title="Auto Telemetry API")


@app.get("/health")
def health():
    return {"status": "ok"}


# TODO: ендпоінти для вивантаження CSV за період та керування
