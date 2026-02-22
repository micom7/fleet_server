"""
Простий Modbus TCP клієнт для тестування симуляторів
"""

import sys
import io
# Налаштування кодування для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pymodbus.client import ModbusTcpClient
import time

def test_et7017(host='localhost', port=5020, unit_id=1):
    """Тест симулятора ET-7017 (аналогові входи)"""
    print(f"\n=== Тест ET-7017 на {host}:{port} ===")
    
    client = ModbusTcpClient(host, port=port)
    
    if not client.connect():
        print(f"❌ Помилка підключення до {host}:{port}")
        return
    
    print(f"✅ Підключено до {host}:{port}")
    
    try:
        # Читаємо Input Registers (function code 04)
        # Реєстри 0-7: AI канали 0-7
        result = client.read_input_registers(address=0, count=8, device_id=unit_id)
        
        if result.isError():
            print(f"[ERROR] Помилка читання: {result}")
        else:
            print(f"[DATA] Аналогові входи (4-20 мА):")
            for i, value in enumerate(result.registers):
                # Конвертація в мА: значення від 6400 (4 мА) до 32000 (20 мА)
                mA = 4 + (value - 6400) / (32000 - 6400) * 16
                print(f"  Канал {i}: {value} (raw) = {mA:.2f} мА")
    
    finally:
        client.close()

def test_et7284(host='localhost', port=5022, unit_id=1):
    """Тест симулятора ET-7284 (лічильник/частота)"""
    print(f"\n=== Тест ET-7284 на {host}:{port} ===")

    client = ModbusTcpClient(host, port=port)

    if not client.connect():
        print(f"❌ Помилка підключення до {host}:{port}")
        return

    print(f"✅ Підключено до {host}:{port}")

    try:
        # Читаємо Input Registers (function code 04), адреси 16–31 (ADR-002)
        # Лічильники: канали 0–3, адреси 16–23 (4 канали × 2 реєстри на 32-bit)
        # Частота:    канали 4–7, адреси 24–31 (4 канали × 2 реєстри на 32-bit)
        result = client.read_input_registers(address=16, count=16, device_id=unit_id)

        if result.isError():
            print(f"[ERROR] Помилка читання: {result}")
            return

        regs = result.registers

        print(f"[DATA] Лічильники (32-bit), канали 0–3:")
        for i in range(4):
            low = regs[i * 2]
            high = regs[i * 2 + 1]
            counter_value = (high << 16) | low
            print(f"  Канал {i}: {counter_value} імпульсів")

        print(f"[DATA] Частота (Гц), канали 4–7:")
        for i in range(4):
            low = regs[8 + i * 2]
            high = regs[8 + i * 2 + 1]
            freq_value = (high << 16) | low
            print(f"  Канал {i + 4}: {freq_value} Гц")

    finally:
        client.close()

if __name__ == "__main__":
    print("=== Тестування симуляторів ICP DAS ===\n")
    
    # Тест ET-7017 #1
    test_et7017('localhost', 5020, 1)
    time.sleep(0.5)
    
    # Тест ET-7017 #2
    test_et7017('localhost', 5021, 1)
    time.sleep(0.5)
    
    # Тест ET-7284
    test_et7284('localhost', 5022, 1)
    
    print("\n[OK] Тестування завершено!")
