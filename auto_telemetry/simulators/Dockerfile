FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY et7017_simulator.py et7284_simulator.py ./

# Команда запуску передається через docker-compose.yml для кожного сервісу окремо
