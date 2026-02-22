# Прив'язка до ПК — план реалізації (RSA-підписана ліцензія)

## Концепція

```
Розробник                              Клієнт (цільовий ПК)
─────────────────────────────────────────────────────────────
1. generate_keys.py
   → private.pem (зберігається у тебе)
   → public.pem  (вбудовується у код)

2. Клієнт запускає collect_fingerprint.py
   → надсилає тобі fingerprint.json

3. Ти запускаєш issue_license.py
   → підписуєш fingerprint.json private.pem
   → надсилаєш клієнту license.dat

4.                                     Кладе license.dat у корінь проекту
5.                                     Запускає run_portal.py / collector
   ← checker.py перевіряє підпис public.pem
   ← збирає поточний відбиток ПК
   ← порівнює → OK або SystemExit
```

**Логіка безпеки:**
- Без твого `private.pem` підписати нову ліцензію неможливо
- `public.pem` вбудований у код — тільки перевіряє, не підписує
- `license.dat` прив'язаний до конкретного заліза — на іншому ПК відбиток не збіжиться

---

## Структура файлів для створення

```
auto_telemetry/
├── license/
│   ├── __init__.py          ← експортує verify_or_exit() (Python, тонка обгортка)
│   ├── _core.pyx            ← Cython-модуль: вся логіка (НЕ входить у дистрибутив)
│   └── _core.pyd            ← скомпільований бінарник (входить у дистрибутив)
│
├── tools/                   ← утиліти розробника (не входять у дистрибутив)
│   ├── generate_keys.py     ← генерація RSA-пари (1 раз)
│   ├── collect_fingerprint.py  ← клієнт запускає це, щоб зібрати відбиток
│   ├── issue_license.py     ← розробник підписує ліцензію
│   └── build_license_core.py   ← компілює _core.pyx → _core.pyd
│
├── keys/                    ← НЕ комітити в git!
│   ├── private.pem          ← тільки у розробника
│   └── public.pem           ← вбудовується у _core.pyx як рядок
│
└── license.dat              ← підписана ліцензія (кладеться на ПК клієнта)
```

> Додати у `.gitignore`: `keys/`, `license.dat`, `tools/`, `license/_core.pyx`, `license/_core.c`

---

## Деталі кожного файлу

### `license/_core.pyx` — Cython-модуль (серце захисту)

Містить **всю критичну логіку** — компілюється у нативний `.pyd`, вихідний код клієнту не передається.

**Що всередині:**

- Константа `_PUBLIC_KEY_PEM` — публічний ключ вбудований прямо у бінарник
- Функція `_collect_fields() -> dict` — збирає апаратні ідентифікатори:

  | Поле           | Джерело (Windows)                     | Примітка                         |
  |----------------|---------------------------------------|----------------------------------|
  | `mac`          | `uuid.getnode()`                      | MAC першого мережевого адаптера  |
  | `disk_serial`  | `wmic diskdrive get SerialNumber`     | Серійник першого диска           |
  | `bios_uuid`    | `wmic csproduct get UUID`             | UUID BIOS/материнської плати     |
  | `hostname`     | `socket.gethostname()`                | Ім'я ПК (для читабельності логу) |

  - Якщо WMI-команда повертає порожній рядок / помилку → підставляти `"UNKNOWN"`

- Функція `verify(license_path: str) -> bool`:
  1. Читає `license.dat` як JSON
  2. Перераховує хеш від поточного заліза: `SHA-256( json.dumps(fields, sort_keys=True) )`
  3. Порівнює з `fingerprint["hash"]` у файлі
  4. Перевіряє RSA-підпис (PSS + SHA-256) вбудованим публічним ключем
  5. Повертає `True` тільки якщо **обидві** перевірки пройшли

- Функція `verify_or_exit(license_path: str)`:
  - Викликає `verify()`, при невдачі — `raise SystemExit(1)`

**Алгоритм підпису:** RSA-PSS + SHA-256 (бібліотека `cryptography`, імпортується у .pyx)

### `license/__init__.py`

Тонка Python-обгортка — лише реекспортує з бінарника:

```python
from ._core import verify_or_exit
```

Клієнт бачить тільки цей рядок; вся логіка — у непрозорому `.pyd`.

### `tools/build_license_core.py`

Скрипт компіляції — запускається розробником перед передачею дистрибутиву:

```
python tools/build_license_core.py
```

Кроки всередині:
1. Викликає `cython license/_core.pyx --embed` → генерує `_core.c`
2. Викликає `python setup_core.py build_ext --inplace` → компілює у `license/_core.pyd`
3. Видаляє проміжні файли `_core.c`, `build/`

Потребує: `cython` і MSVC або MinGW на машині розробника.

### `tools/generate_keys.py`

- Генерує RSA 2048-bit пару
- Зберігає `keys/private.pem` і `keys/public.pem`
- **Запускається один раз розробником**
- Виводить підказку: скопіювати вміст `keys/public.pem` у константу `_PUBLIC_KEY_PEM` у `_core.pyx`

### `tools/collect_fingerprint.py`

- **Запускається на цільовому ПК клієнтом** (чистий Python, без залежностей окрім stdlib)
- Не імпортує `license/_core` — збирає відбиток самостійно тими самими командами
- Зберігає у `fingerprint.json` і виводить у консоль
- Клієнт надсилає цей файл розробнику

### `tools/issue_license.py`

- **Запускається розробником** з аргументом `--input fingerprint.json`
- Читає `keys/private.pem`
- Підписує `json.dumps(fingerprint["fields"], sort_keys=True).encode()`
- Формує `license.dat`:

```json
{
  "fingerprint": {
    "fields": { "mac": "...", "disk_serial": "...", "bios_uuid": "...", "hostname": "..." },
    "hash": "sha256_hex..."
  },
  "signature": "base64_encoded_rsa_signature",
  "issued_at": "2026-02-22T00:00:00Z",
  "comment": "ТОВ Клієнт, ПК оператора №1"
}
```

### `tools/generate_keys.py`

- Генерує RSA 2048-bit пару
- Зберігає `keys/private.pem` і `keys/public.pem`
- **Запускається один раз розробником**
- Виводить підказку: скопіювати вміст `public.pem` у `checker.py`

### `tools/collect_fingerprint.py`

- **Запускається на цільовому ПК клієнтом**
- Збирає `fingerprint.collect()`
- Зберігає у `fingerprint.json` і виводить у консоль
- Клієнт надсилає цей файл розробнику

### `tools/issue_license.py`

- **Запускається розробником** з аргументом `--input fingerprint.json`
- Читає `keys/private.pem`
- Підписує `json.dumps(fingerprint["fields"], sort_keys=True).encode()`
- Формує `license.dat`:

```json
{
  "fingerprint": {
    "fields": { "mac": "...", "disk_serial": "...", "bios_uuid": "...", "hostname": "..." },
    "hash": "sha256_hex..."
  },
  "signature": "base64_encoded_rsa_signature",
  "issued_at": "2026-02-22T00:00:00Z",
  "comment": "ТОВ Клієнт, ПК оператора №1"
}
```

---

## Точки інтеграції в існуючий код

### `run_portal.py`
Додати **першим рядком** у `if __name__ == "__main__"`:

```python
from license import verify_or_exit
verify_or_exit()
```

Перевірка відбувається до старту сервера і відкриття вікна.

### `collector/main.py`
Аналогічно — додати перевірку **на самому початку** `if __name__ == "__main__"` (або у функції запуску).

---

## Залежності

Додати у `requirements.txt` (для роботи програми):
```
cryptography>=42.0
```

Тільки на машині розробника (для збірки, не для клієнта):
```
cython>=3.0
```

`wmic` вже є у Windows, MSVC встановлюється разом з Visual Studio Build Tools (безкоштовно).

---

## Процедура підготовки та видачі ліцензії (покрокова)

```
── Один раз (підготовка) ────────────────────────────────────────────

Крок 1: Генерація ключів
  python tools/generate_keys.py
  → keys/private.pem  (зберігати тільки у себе, не передавати)
  → keys/public.pem

Крок 2: Вбудувати публічний ключ у Cython-модуль
  Скопіювати вміст keys/public.pem у константу _PUBLIC_KEY_PEM у license/_core.pyx

Крок 3: Скомпілювати бінарник
  python tools/build_license_core.py
  → license/_core.pyd  (це і є захищений бінарник)

── На кожного нового клієнта ────────────────────────────────────────

Крок 4 (клієнт):
  python tools/collect_fingerprint.py
  → надіслати fingerprint.json розробнику

Крок 5 (розробник):
  python tools/issue_license.py --input fingerprint.json --comment "Назва клієнта"
  → надіслати клієнту license.dat

Крок 6 (клієнт):
  Покласти license.dat у корінь проекту (поруч з run_portal.py)
  Запустити — програма стартує нормально.

── Що передається клієнту ───────────────────────────────────────────

  ✓ весь проект (портал, колектор, конфіги)
  ✓ license/_core.pyd  (бінарник)
  ✓ license/__init__.py
  ✓ license.dat
  ✗ license/_core.pyx  (вихідний код — не передавати)
  ✗ keys/              (ключі — не передавати)
  ✗ tools/             (утиліти розробника — не передавати)
```

---

## Поведінка при відсутності / невалідній ліцензії

| Ситуація                              | Результат                                     |
|---------------------------------------|-----------------------------------------------|
| `license.dat` відсутній               | Виведення повідомлення + `SystemExit(1)`      |
| `license.dat` пошкоджений (не JSON)   | Виведення повідомлення + `SystemExit(1)`      |
| Відбиток не збігається (інший ПК)     | Виведення повідомлення + `SystemExit(1)`      |
| Підпис невалідний (підроблений файл)  | Виведення повідомлення + `SystemExit(1)`      |
| Всі перевірки пройшли                 | Нормальний старт, нічого не виводить          |

---

## Що НЕ захищає цей метод

- Зловмисник з IDA Pro / Ghidra може знайти у бінарнику перевірку і **запатчити `.pyd`** (байт-патч) — але це вимагає значної кваліфікації
- Видалення рядка `from ._core import verify_or_exit` у `__init__.py` і підміна на `def verify_or_exit(): pass` — обходить перевірку; захист: **PyInstaller** упаковує всі `.py` разом з `.pyd`, ускладнюючи підміну
- Серійник диска може змінитись після заміни диска → клієнт просто отримує нову ліцензію

---

## Файли, що змінюються в існуючому коді

| Файл                   | Зміна                                                        |
|------------------------|--------------------------------------------------------------|
| `run_portal.py`        | +2 рядки на початку `__main__`                               |
| `collector/main.py`    | +2 рядки на початку `__main__`                               |
| `requirements.txt`     | +1 рядок: `cryptography>=42.0`                               |
| `.gitignore`           | `keys/`, `license.dat`, `tools/`, `license/_core.pyx`, `license/_core.c` |

---

## Рівні захисту (підсумок)

```
RSA-ліцензія                → не можна підробити license.dat
+ Cython (.pyd бінарник)    → логіку і публічний ключ важко витягти
+ PyInstaller (опційно)     → важко знайти точку підміни __init__.py
─────────────────────────────────────────────────────────────────────
Результат: захист від копіювання для 99% реальних сценаріїв
```
