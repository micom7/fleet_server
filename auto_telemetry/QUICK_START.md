# Швидкий старт: Запуск симуляторів та тестування

## Локальний запуск (без Docker)

### 1. Встановити залежності:
```bash
cd f:\auto_telemetry\simulators
pip install -r requirements.txt
```

### 2. Запустити симулятори в окремих терміналах:

**Термінал 1** - ET-7017 #1:
```bash
python f:\auto_telemetry\simulators\et7017_simulator.py 5020 1
```

**Термінал 2** - ET-7017 #2:
```bash
python f:\auto_telemetry\simulators\et7017_simulator.py 5021 1
```

**Термінал 3** - ET-7284:
```bash
python f:\auto_telemetry\simulators\et7284_simulator.py 5022 1 1000
```

### 3. Запустити API (опціонально):
```bash
cd f:\auto_telemetry\api
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

---

## Тестування через Modbus клієнт

### Параметри підключення:

#### ET-7017 #1:
- **IP:** `localhost` (або `127.0.0.1`)
- **Port:** `5020`
- **Unit ID:** `1`
- **Function:** `04` (Read Input Registers)
- **Address:** `0-7` (8 каналів)

#### ET-7017 #2:
- **IP:** `localhost`
- **Port:** `5021`
- **Unit ID:** `1`
- **Function:** `04` (Read Input Registers)
- **Address:** `0-7`

#### ET-7284:
- **IP:** `localhost`
- **Port:** `5022`
- **Unit ID:** `1`
- **Function:** `03` (Read Holding Registers)
- **Лічильники:** Address `0-7` (4 канали × 2 реєстри)
- **Частота:** Address `8-15` (4 канали × 2 реєстри)

---

## Тестування через Python клієнт

```bash
cd f:\auto_telemetry\simulators
python test_client.py
```

Автоматично підключиться до всіх симуляторів і виведе поточні значення.

---

## Тестування через інші Modbus клієнти

### Modbus Poll (Windows):
1. Відкрити Modbus Poll
2. Connection → Connect
3. Ввести:
   - IP: `127.0.0.1`
   - Port: `5020` (або `5021`, `5022`)
   - Unit ID: `1`
4. Встановити:
   - Function: `04` для ET-7017 або `03` для ET-7284
   - Address: `0`
   - Quantity: `8` для ET-7017, `16` для ET-7284

### QModMaster (крос-платформенний):
1. File → New
2. Connection → TCP/IP
3. Ввести IP та Port
4. Встановити Function та Address

### modbus-cli (командний рядок):
```bash
# Встановити: pip install modbus-cli

# Читати ET-7017
modbus read localhost 5020 1 4 0 8

# Читати ET-7284 (лічильники)
modbus read localhost 5022 1 3 0 8
```

---

## Перевірка роботи

### Очікувані результати:

**ET-7017:**
- Значення Input Registers: від `6400` до `32000` (відповідає 4-20 мА)
- Значення змінюються з часом (невеликі коливання)

**ET-7284:**
- Лічильники (реєстри 0-7): збільшуються з часом (симуляція руху)
- Частота (реєстри 8-15): показує частоту в Гц (залежить від швидкості)

---

## Усунення проблем

### Симулятор не запускається:
```bash
# Перевірити, чи порт вільний
netstat -an | findstr "5020 5021 5022"
```

### Помилка підключення:
- Перевірити, що симулятор запущений
- Перевірити firewall (порти 5020-5022)

### Неправильні значення:
- Перевірити Unit ID (має бути `1`)
- Перевірити Function Code (`04` для ET-7017, `03` для ET-7284)
- Перевірити Address (починається з `0`)
