# Система синхронізації і оновлення — план реалізації

## Концепція

Ініціатор з'єднання — **сервер**. Клієнт пасивно слухає.
При кожному підключенні сервер виконує два завдання в одному сеансі:

```
Сервер (розробник/адмін)              Клієнт (цільовий ПК, agent)
──────────────────────────────────────────────────────────────────
1. Ініціює підключення до клієнта
2. Підписаний challenge → клієнт      ← агент перевіряє підпис
                                         (автентифікація сервера)
   ← архів даних (з останньої синхр.) 3. Агент пакує і надсилає дані
4. Якщо є оновлення → пакет update       (стисло, з мітками часу)
                                      5. Агент зберігає пакет
                                         сповіщає portal: "є оновлення"
                                      6. Оператор бачить у UI → підтверджує
                                      7. Watchdog застосовує оновлення
```

**Ключові принципи:**
- Клієнт **не звертається** до сервера самостійно — тільки слухає
- Сервер автентифікує себе підписом (`private.pem`) — агент перевіряє (`public.pem`)
- Оновлення зберігається локально до підтвердження оператора
- Один сеанс = забрати дані + (опційно) доставити оновлення

---

## Структура файлів

```
auto_telemetry/
│
├── agent/                            ← агент на ПК клієнта (пасивний слухач)
│   ├── __init__.py
│   ├── server.py                     ← FastAPI-мікросервер на порту 9876
│   ├── authenticator.py              ← перевірка підпису сервера
│   ├── exporter.py                   ← пакування архіву даних для сервера
│   └── incoming_update.py            ← приймання пакету і сповіщення portal
│
├── updater/                          ← модуль оновлення (без зміни)
│   ├── verifier.py                   ← перевірка RSA-підпису пакету
│   ├── patcher.py                    ← заміна файлів
│   ├── migrator.py                   ← SQL-міграції
│   └── backup.py                     ← резервна копія
│
├── watchdog.py                       ← запускає collector + portal + agent
│
├── portal/
│   └── main.py                       ← +3 ендпоінти: status / apply / progress
│
├── pending_update/                   ← тимчасова директорія
│   └── update_v1.2.0.zip             ← пакет, що чекає підтвердження оператора
│
└── backups/
    └── backup_v1.1.0_20260222.zip

── На сервері розробника ─────────────────────────────────────────────

server_tools/
├── sync_client.py                    ← підключається до агентів, тягне дані, пушить оновлення
├── publish.py                        ← пакує і підписує update_vX.Y.Z.zip
└── data_storage/                     ← отримані від клієнтів архіви даних
```

---

## Протокол сеансу (HTTPS REST)

Агент слухає на `https://0.0.0.0:9876`. Сервер ініціює з'єднання.

### Крок 1 — автентифікація сервера

```
POST /auth
Body: {
  "timestamp": "2026-02-22T10:00:00Z",
  "signature": "<base64: RSA-PSS підпис timestamp через private.pem>"
}

Response 200: { "session_token": "<UUID, дійсний 5 хв>" }
Response 401: { "error": "invalid signature" }
```

Агент перевіряє підпис публічним ключем (`UPDATE_PUBLIC_KEY_PEM`, вбудований у `authenticator.py`).
Усі наступні запити містять `Authorization: Bearer <session_token>`.

### Крок 2 — сервер забирає архів даних

```
GET /data/export?since=2026-02-20T00:00:00Z
Authorization: Bearer <token>

Response 200: binary stream (gzip-архів)
  Content-Type: application/gzip
  X-Record-Count: 14523
  X-Period-End: 2026-02-22T10:00:00Z
```

Агент викликає `exporter.export(since)` → стискає → надсилає.
Сервер зберігає архів у `data_storage/<client_id>/<timestamp>.gz`.

### Крок 3 — сервер надсилає оновлення (якщо є)

```
POST /update
Authorization: Bearer <token>
Content-Type: application/zip
X-Update-Version: 1.2.0
X-Manifest-Signature: <base64>

Body: binary (update_v1.2.0.zip)

Response 200: { "status": "queued" }       ← прийнято, чекає оператора
Response 409: { "status": "same_version" } ← вже актуальна версія
Response 400: { "status": "invalid_sig" }  ← підпис не пройшов
```

Агент:
1. Перевіряє підпис маніфесту через `verifier.verify_package()`
2. Зберігає у `pending_update/update_v1.2.0.zip`
3. Пише `pending_update/meta.json` з версією і notes
4. Сповіщає portal через внутрішню чергу → SSE до UI оператора

---

## Деталі компонентів

### `agent/server.py`

FastAPI-застосунок на порту 9876 (окремий від portal на 8000).

- Три ендпоінти: `POST /auth`, `GET /data/export`, `POST /update`
- Сесійні токени зберігаються in-memory, TTL 5 хвилин
- Rate limiting: не більше 3 спроб `/auth` за хвилину з однієї IP
- Логує кожен сеанс: час, IP сервера, кількість записів, версія оновлення

### `agent/authenticator.py`

- Містить `SERVER_PUBLIC_KEY_PEM` — той самий публічний ключ, що у `license/_core.pyx`
- Функція `verify_server(timestamp: str, signature: str) -> bool`:
  - Перевіряє RSA-PSS підпис рядка `timestamp`
  - Перевіряє що `timestamp` не старіший за 60 секунд (захист від replay-атак)

### `agent/exporter.py`

- Функція `export(since: datetime, dsn: str) -> bytes`:
  1. Запитує з PostgreSQL записи з `readings` де `time > since`
  2. Серіалізує у JSON Lines (одна JSON-строчка = один запис)
  3. Стискає через `gzip`
  4. Повертає bytes для стримінгу
- Функція `get_last_export_time() -> datetime` — читає з файлу `agent/last_sync.txt`
- Записує новий `last_sync.txt` після успішного експорту

### `agent/incoming_update.py`

- Функція `receive(zip_bytes, version, manifest_sig) -> bool`:
  1. Перевіряє підпис через `verifier.verify_package()`
  2. Порівнює версію з поточною (`version.txt`) — якщо та сама, повертає `False`
  3. Зберігає zip у `pending_update/`
  4. Пише `pending_update/meta.json`
  5. Кладе повідомлення у `asyncio.Queue` → portal зчитує і шле SSE операторові

### `agent/__init__.py`

```python
def start():
    """Запускається watchdog-ом як окремий процес."""
    uvicorn.run(app, host="0.0.0.0", port=9876, ssl_keyfile=..., ssl_certfile=...)
```

---

### Інтеграція у `portal/main.py`

Три нові ендпоінти (захищені CONFIG_PIN):

#### `GET /api/update/status`
```json
{
  "current_version": "1.1.0",
  "pending_update": true,
  "pending_version": "1.2.0",
  "notes": "Додано журнал тривог.",
  "received_at": "2026-02-22T10:05:00Z"
}
```

#### `POST /api/update/apply`
- Перевіряє PIN
- Запускає `apply_update()` у фоновому потоці

`apply_update()` — послідовність з атомарним відкатом:

```
1. verify     — перевірити підпис пакету ще раз (захист від підміни файлу на диску)
2. backup     — створити backups/backup_vX.Y.Z_<timestamp>.zip (поточний стан)
3. patch      — замінити файли з files/ (не чіпати захищені файли)
4. write_ver  — записати нову версію у version.txt
5. migrate    — виконати SQL-міграції з migrations/ по порядку (за іменем файлу)
6. flag       — видалити restart.flag якщо є, створити новий
               (видалення ПЕРЕД записом — watchdog не зациклюється при краші)

При будь-якій помилці на кроках 3-5:
  → restore backup (розпакувати резервну копію)
  → записати failure у agent/update_log.jsonl
  → надіслати SSE: {"step": "failed", "msg": "..."}
  → НЕ ставити restart.flag
```

#### `GET /api/update/progress` (SSE)
```
data: {"step": "verify",   "pct": 15, "msg": "Перевірка пакету..."}
data: {"step": "backup",   "pct": 30, "msg": "Резервна копія..."}
data: {"step": "patch",    "pct": 60, "msg": "Застосування файлів..."}
data: {"step": "version",  "pct": 70, "msg": "Запис версії..."}
data: {"step": "migrate",  "pct": 85, "msg": "Міграція БД..."}
data: {"step": "done",     "pct": 100,"msg": "Перезапуск..."}
data: {"step": "failed",   "pct": 0,  "msg": "Помилка: <деталі>. Відновлено резервну копію."}
```

**UI у порталі:**
- Бейдж "Отримано оновлення vX.Y.Z" у хедері
- Модальне вікно: версія, notes, "Застосувати" / "Пізніше"
- Прогрес-бар під час оновлення
- Після `done` — авто-релоад сторінки через 10 с

---

### `watchdog.py`

Запускає чотири процеси (з урахуванням outbound):

```
watchdog.py
├── collector/main.py    ← перезапускає при падінні
├── portal (port 8000)   ← перезапускає при падінні
├── outbound (port 8001) ← перезапускає при падінні
└── agent  (port 9876)   ← перезапускає при падінні

Стежить за restart.flag → graceful restart всіх чотирьох
```

Перевірка ліцензії — один раз у watchdog при старті.

**Логіка `restart.flag`:**
```python
# watchdog.py — головний цикл
flag = Path("restart.flag")
if flag.exists():
    flag.unlink()          # видалити ДО перезапуску
    restart_all_services() # якщо тут крашнеться — прапора вже немає, немає циклу
```

> Прапор видаляється **перед** перезапуском, а не після. При краші watchdog під час
> перезапуску прапор не збережеться — немає ризику нескінченного restart-циклу.

---

### `server_tools/sync_client.py` (на сервері розробника)

```
python server_tools/sync_client.py --host 192.168.1.100 --client-id plant_A
```

Аргументи:
- `--host` — IP цільового ПК
- `--client-id` — ім'я для збереження даних
- `--update` — (опційно) шлях до zip-пакету оновлення

Кроки:
1. `POST /auth` — підписує поточний timestamp `private.pem` → отримує токен
2. `GET /data/export?since=...` → зберігає у `data_storage/<client_id>/<ts>.gz`
3. Якщо `--update`: `POST /update` → надсилає пакет

### `server_tools/publish.py`

```
python server_tools/publish.py \
  --version 1.2.0 \
  --files portal/main.py collector/normalizer.py \
  --migrations migrations/0012_add_alarms.sql \
  --notes "Додано журнал тривог."
```

Формує підписаний `update_v1.2.0.zip` готовий для передачі через `sync_client.py`.

---

## Формат пакету оновлення (без змін)

```
update_v1.2.0.zip
├── manifest.json          ← версія, файли, міграції, notes
├── manifest.sig           ← RSA-PSS підпис manifest.json
├── files/
│   └── ...                ← нові/змінені файли
└── migrations/
    └── 0012_add_alarms.sql
```

**Що ніколи не замінюється:**
`license/_core.pyd`, `license/__init__.py`, `license.dat`, `config.txt`, `credentials.env`,
`agent/cert.pem`, `agent/key.pem` (TLS-сертифікат агента унікальний для кожної машини)

---

## Конфігурація (у `config.txt`)

```ini
AGENT_PORT        = 9876
AGENT_CERT_FILE   = agent/cert.pem    # self-signed TLS-сертифікат
AGENT_KEY_FILE    = agent/key.pem
```

TLS-сертифікат генерується один раз на ПК клієнта:
```
openssl req -x509 -newkey rsa:2048 -keyout agent/key.pem -out agent/cert.pem -days 3650 -nodes
```

---

## Процедура синхронізації (покрокова)

```
── Підготовка (один раз) ─────────────────────────────────────────────

1. На ПК клієнта: згенерувати TLS-сертифікат для агента
2. Запустити систему через watchdog.py

── Регулярна синхронізація ───────────────────────────────────────────

3. Адмін (сервер) запускає sync_client.py --host <IP клієнта>
   → /auth: сервер автентифікується
   → /data/export: забирає архів нових даних
   (без оновлення — на цьому кінець)

── Доставка оновлення ────────────────────────────────────────────────

4. Адмін готує пакет:
   python server_tools/publish.py --version 1.2.0 ...

5. Адмін запускає sync з оновленням:
   python server_tools/sync_client.py --host <IP> --update update_v1.2.0.zip
   → /auth → /data/export → /update (пакет доставлено)

6. На ПК клієнта: portal сповіщає оператора "Отримано оновлення"
7. Оператор читає notes → натискає "Застосувати"
8. Система оновлюється, watchdog перезапускає сервіси
```

---

## Залежності (нові)

Додати у `requirements.txt`:
```
httpx>=0.27      # HTTP-клієнт у server_tools/sync_client.py (на сервері)
```

Агент використовує `uvicorn` і `fastapi` — вже є у проекті.

---

## Файли, що змінюються в існуючому коді

| Файл              | Зміна                                                           |
|-------------------|-----------------------------------------------------------------|
| `portal/main.py`  | +3 ендпоінти (status / apply / progress) + SSE-черга           |
| `watchdog.py`     | +запуск agent і outbound як 3-го і 4-го процесів               |
| `config.txt`      | +AGENT_PORT, AGENT_CERT_FILE, AGENT_KEY_FILE, OUTBOUND_PORT    |
| `requirements.txt`| без змін (httpx тільки на сервері)                             |

**Нові файли:**

| Файл                    | Призначення                                            |
|-------------------------|--------------------------------------------------------|
| `version.txt`           | поточна версія, читається `/status` і `incoming_update.py` |
| `agent/update_log.jsonl`| журнал всіх спроб оновлень (успіх/невдача, версія, час) |

---

## Підсумок потоку

```
[Адмін ініціює]
    sync_client.py → POST /auth (підпис private.pem)
                   → GET /data/export  → дані збережено на сервері
                   → POST /update      → пакет доставлено агенту

[Агент на клієнті]
    verifier → підпис OK
    → зберігає pending_update/
    → сповіщає portal через asyncio.Queue

[Оператор підтверджує]
    portal UI → "Отримано v1.2.0" → "Застосувати"
    → verify → backup → patch → write version.txt → migrate
    → при помилці: restore backup, SSE "failed", зупинитись
    → при успіху: restart.flag (видаляємо старий якщо є, пишемо новий)
                  SSE "done"

[Watchdog]
    → виявляє restart.flag
    → flag.unlink()  ← видаляємо ДО перезапуску
    → перезапуск collector + portal + outbound + agent
    → UI авто-релоад → нова версія працює
    → /status повертає нову version.txt → fleet_server оновлює vehicles.software_version
```

---

## Журнал оновлень (`agent/update_log.jsonl`)

Кожна спроба оновлення дописує один JSON-рядок:

```json
{"time": "2026-02-22T10:10:00Z", "from_version": "1.1.0", "to_version": "1.2.0", "status": "ok"}
{"time": "2026-02-23T09:00:00Z", "from_version": "1.2.0", "to_version": "1.3.0", "status": "failed", "error": "migration 0013: column already exists"}
```

Не ротується автоматично — для парку 10 машин зростає повільно (рядок на оновлення).
