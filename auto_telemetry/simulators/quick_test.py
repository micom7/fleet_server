"""Швидкий тест підключення до ET-7017"""
from pymodbus.client import ModbusTcpClient
import time

print("Підключення до ET-7017 на localhost:5020...")
client = ModbusTcpClient(host='localhost', port=5020)

if client.connect():
    print("OK - Підключено!")
    # Встановлюємо device_id через параметр у методі
    result = client.read_input_registers(address=0, count=8, device_id=1)
    if not result.isError():
        print(f"Реєстри (8 каналів): {result.registers}")
        for i, val in enumerate(result.registers):
            mA = 4 + (val - 6400) / (32000 - 6400) * 16
            print(f"  Канал {i}: {val} = {mA:.2f} мА")
    else:
        print(f"Помилка читання: {result}")
    client.close()
else:
    print("FAIL - Не вдалося підключитися!")
    print("Перевірте, чи запущений симулятор: python et7017_simulator.py 5020 1")
