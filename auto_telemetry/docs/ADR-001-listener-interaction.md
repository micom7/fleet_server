# ADR-001: Взаємодія Collector → Monitor → Portal через ZeroMQ слухачів

**Статус:** Прийнято
**Дата:** 2026-02-18
**Автори:** команда auto_telemetry

---

## Контекст

Система складається з трьох незалежних процесів:
- **Collector** — опитує ICP DAS модулі (1 Гц), нормалізує сигнали, пише в БД
- **Monitor** — виявляє аномалії в реальному часі, публікує тривоги
- **Portal** — операторський UI (FastAPI + SSE), відображає стан в браузері

Потрібно вирішити як ці процеси обмінюються даними в реальному часі **без прямих HTTP-викликів між сервісами** і **без polling БД**.

## Рішення

Використовуємо **ZeroMQ PUB/SUB** з двома незалежними шинами:

```
Collector ──PUB:5555──► Monitor (SUB)
                    ──► Portal  (SUB)  ← Collector Listener

Monitor   ──PUB:5556──► Portal  (SUB)  ← Monitor Listener

Portal ──SSE──► Browser
```

Portal тримає **два фонові async завдання** (listeners), кожен з яких незалежно читає свою ZeroMQ шину.

## Деталі протоколу

### 1. Шина даних: Collector → всі (порт 5555)

**Тип ZeroMQ:** `PUB` на стороні Collector, `SUB` на стороні Monitor та Portal
**Env-змінна:** `ZMQ_COLLECTOR_PUB=tcp://127.0.0.1:5555`

**Topic фільтр:** `data` (байтовий префікс)

**Формат повідомлення** (JSON після topic-байту):
```json
{
  "cycle_time": "2024-01-01T12:00:00.123Z",
  "readings": [
    {"channel_id": 1, "value": 12.54},
    {"channel_id": 2, "value": 4.80},
    {"channel_id": 3, "value": 0.0}
  ]
}
```

| Поле | Тип | Опис |
|---|---|---|
| `cycle_time` | ISO 8601 UTC | Час початку циклу опитування (однаковий для всіх каналів циклу) |
| `readings[].channel_id` | int | ID каналу з `channel_config` |
| `readings[].value` | float \| null | Нормалізоване фізичне значення; `null` якщо помилка читання |

**Частота:** 1 повідомлення/секунду (один пакет на цикл опитування)

---

### 2. Шина тривог: Monitor → Portal (порт 5556)

**Тип ZeroMQ:** `PUB` на стороні Monitor, `SUB` на стороні Portal
**Env-змінна:** `ZMQ_MONITOR_PUB=tcp://127.0.0.1:5556`

**Topic фільтр:** `alarm` (байтовий префікс)

**Формат повідомлення** (JSON після topic-байту):
```json
{
  "event": "triggered",
  "alarm_id": 42,
  "rule_id": 5,
  "channel_id": 3,
  "alarm_type": "high_limit",
  "value": 18.20,
  "threshold": 15.0,
  "severity": "critical",
  "message": "Тиск масла перевищено",
  "triggered_at": "2024-01-01T12:00:01.456Z"
}
```

**Другий варіант події — скасування тривоги:**
```json
{
  "event": "resolved",
  "alarm_id": 42,
  "resolved_at": "2024-01-01T12:05:00.000Z"
}
```

| Поле | Значення | Опис |
|---|---|---|
| `event` | `triggered` / `resolved` | Тип події тривоги |
| `alarm_type` | `high_limit` / `low_limit` / `rate_of_change` / `std_deviation` | Тип аномалії |
| `severity` | `warning` / `critical` | Рівень серйозності |

---

### 3. Collector Listener у Portal

Фонова async-задача FastAPI, підписана на `ZMQ_COLLECTOR_PUB`.

**Відповідальність:**
- Отримує кожен пакет даних від Collector
- Оновлює in-memory стан `current_values: dict[int, float]` (channel_id → value)
- Пушить SSE-подію `data` до всіх активних SSE-клієнтів

**Псевдокод:**
```python
async def collector_listener(state: AppState, sse_queue: asyncio.Queue):
    ctx = zmq.asyncio.Context()
    sock = ctx.socket(zmq.SUB)
    sock.connect(settings.ZMQ_COLLECTOR_PUB)
    sock.setsockopt(zmq.SUBSCRIBE, b"data")

    while True:
        try:
            [topic, payload] = await sock.recv_multipart()
            packet = json.loads(payload)
            for r in packet["readings"]:
                state.current_values[r["channel_id"]] = r["value"]
            await sse_queue.put({"event": "data", "data": packet})
        except Exception as e:
            logger.error("collector_listener error: %s", e)
            await asyncio.sleep(1)   # короткий backoff перед retry
```

---

### 4. Monitor Listener у Portal

Фонова async-задача FastAPI, підписана на `ZMQ_MONITOR_PUB`.

**Відповідальність:**
- Отримує події тривог від Monitor
- При `triggered`: додає тривогу до `active_alarms: dict[int, AlarmEvent]`
- При `resolved`: видаляє тривогу з `active_alarms`
- Пушить SSE-подію `alarm` до всіх активних SSE-клієнтів

**Псевдокод:**
```python
async def monitor_listener(state: AppState, sse_queue: asyncio.Queue):
    ctx = zmq.asyncio.Context()
    sock = ctx.socket(zmq.SUB)
    sock.connect(settings.ZMQ_MONITOR_PUB)
    sock.setsockopt(zmq.SUBSCRIBE, b"alarm")

    while True:
        try:
            [topic, payload] = await sock.recv_multipart()
            event = json.loads(payload)
            if event["event"] == "triggered":
                state.active_alarms[event["alarm_id"]] = event
            elif event["event"] == "resolved":
                state.active_alarms.pop(event["alarm_id"], None)
            await sse_queue.put({"event": "alarm", "data": event})
        except Exception as e:
            logger.error("monitor_listener error: %s", e)
            await asyncio.sleep(1)
```

---

### 5. In-memory стан Portal

```python
@dataclass
class AppState:
    current_values: dict[int, float | None] = field(default_factory=dict)
    # {channel_id: normalized_value}

    active_alarms: dict[int, dict] = field(default_factory=dict)
    # {alarm_id: alarm_event_dict}
```

Цей стан **не персистентний** між перезапусками Portal. При перезапуску:
- `current_values` наповнюється з першого ж пакету від Collector (протягом 1 сек)
- `active_alarms` наповнюється з наступних подій від Monitor; **для відновлення активних тривог після рестарту Portal читає `alarms_log` з БД при старті**

---

### 6. SSE Stream у Portal

SSE endpoint `/stream` мультиплексує обидві шини в один потік до браузера:

```
data: {"event": "data",  "payload": {...}}   ← від Collector Listener
data: {"event": "alarm", "payload": {...}}   ← від Monitor Listener
data: {"event": "heartbeat"}                 ← кожні 5 сек (Portal)
```

Браузер отримує **єдиний SSE-потік** і розрізняє події за полем `event`.

---

### 7. Порядок запуску та залежності

```
PostgreSQL  ──► Collector  ──► (порт 5555 готовий)
                               ──► Monitor  (SUB від Collector)
                               ──► Portal   (SUB від Collector)
                Monitor    ──► (порт 5556 готовий)
                               ──► Portal   (SUB від Monitor)
```

**Важливо:** ZeroMQ SUB може підключатися до PUB **до того, як PUB запущено** — це нормально. ZeroMQ буферизує підключення. Listener'и можуть стартувати в будь-якому порядку відносно Collector/Monitor.

---

### 8. Обробка помилок та відновлення

| Ситуація | Поведінка |
|---|---|
| Collector не відповідає (немає пакетів) | Portal не отримує `data` → SSE heartbeat продовжується → браузер показує "Offline" після 3 сек |
| Monitor не відповідає | Portal не отримує `alarm` → поточні тривоги залишаються в `active_alarms` незмінними |
| Виняток у Listener | `asyncio.sleep(1)` + continue (loop не завершується) |
| Portal перезапускається | Listeners стартують заново; `active_alarms` відновлюється з `alarms_log` БД |
| Collector перезапускається | Monitor/Portal автоматично отримають новий потік (ZeroMQ reconnect) |

---

## Обґрунтування вибору ZeroMQ PUB/SUB

| Альтернатива | Чому відхилено |
|---|---|
| HTTP polling від Portal до Collector | Затримка 1+ сек, зв'язування сервісів через HTTP |
| Shared memory / Redis Pub/Sub | Додаткова залежність (Redis); ZeroMQ — вбудований брокер |
| PostgreSQL `LISTEN/NOTIFY` для реалтайм даних | Підходить для конфігів, але не для 1 Гц потоку вимірювань |
| Kafka / RabbitMQ | Надмірно для embedded-системи на ASUS NUC |

**ZeroMQ PUB/SUB обрано тому що:**
- Zero broker — немає додаткового процесу для підтримки
- Нативна async підтримка (`zmq.asyncio`) — seamless інтеграція з FastAPI
- Fan-out з одного PUB до N SUB без змін у Collector/Monitor
- Мінімальна затримка (< 1 мс на localhost)
- Достатньо для масштабу: 1 PUB, 2 SUB на localhost

---

## Наслідки рішення

**Позитивні:**
- Collector і Monitor не знають про Portal — слабке зв'язування
- Portal може перезапускатися незалежно без впливу на збір даних
- Легко додати нового підписника (наприклад, logging service) без змін у Publisher'ах

**Негативні / обмеження:**
- ZeroMQ PUB/SUB не гарантує доставку (fire-and-forget) — пропущені пакети під час рестарту Portal не відновлюються
- In-memory стан Portal втрачається при рестарті (частково вирішується читанням з БД)
- Порти 5555/5556 — конфігурується через `.env`, змінювати тільки при конфліктах

---

## Що НЕ входить у цю специфікацію

- Формат Modbus-запитів до ICP DAS (→ специфікація Collector)
- Алгоритми виявлення аномалій у Monitor (→ специфікація Monitor)
- CRUD конфігів через Portal HTTP (→ специфікація Portal API)
- Схема SSE-повідомлень для браузерного JS (→ специфікація Portal Frontend)
