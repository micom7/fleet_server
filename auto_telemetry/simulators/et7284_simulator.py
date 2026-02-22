"""
Симулятор ICP DAS ET-7284
4/8-канальний лічильник/частота/енкодер (32-bit), 4 цифрові виходи
Modbus TCP сервер (pymodbus 3.12+)
"""

import time
import threading
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusDeviceContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock
import logging

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger(__name__)


class ET7284Simulator:
    """
    Симулятор ET-7284: лічильник/частота/енкодер (32-bit)
    Modbus Input Registers (function code 04), згідно офіційної специфікації ICP DAS:
    - Адреси 16-23: Канали 0-3 як лічильники (32-bit: Low word + High word на канал)
    - Адреси 24-31: Канали 4-7 як частота (32-bit: Low word + High word на канал)

    Канал n (лічильник): адреса = 16 + n*2 (Low), 16 + n*2 + 1 (High)
    Канал n (частота):   адреса = 24 + n*2 (Low), 24 + n*2 + 1 (High)

    Для енкодера: лічильник збільшується з часом (симуляція руху)
    """

    def __init__(self, port=502, unit_id=1, ppm=1000):
        self.port = port
        self.unit_id = unit_id
        self.ppm = ppm  # Pulses Per Metre

        # Input Registers (FC04): адреси 16-31 (8 каналів × 2 реєстри)
        # Блок оголошується з адреси 0, розміром 32 — щоб покрити адреси 0..31
        store = ModbusDeviceContext(
            di=ModbusSequentialDataBlock(0, [0]*4),   # Digital Inputs
            co=ModbusSequentialDataBlock(0, [0]*4),   # Digital Outputs (Coils)
            hr=ModbusSequentialDataBlock(0, [0]*32),  # Holding Registers (конфігурація типу каналів тощо)
            ir=ModbusSequentialDataBlock(0, [0]*33),  # +1 через off-by-one в pymodbus 3.12 verifyAddress
        )

        self.context = ModbusServerContext(devices={unit_id: store}, single=False)

        # Стан лічильників (32-bit значення)
        self.counters = [0] * 4
        self.frequencies = [0] * 4

        # Параметри симуляції руху
        self.speed_mps = [0.5, 0.0, 0.0, 0.0]  # Швидкість в м/с для кожного каналу

    def update_counter_values(self):
        """Оновлює значення лічильників та частоти (симуляція руху енкодера)"""
        last_time = time.time()

        while True:
            current_time = time.time()
            dt = current_time - last_time
            last_time = current_time

            store = self.context[self.unit_id]

            for channel in range(4):
                if self.speed_mps[channel] > 0:
                    pulses_per_second = self.speed_mps[channel] * self.ppm
                    self.counters[channel] += int(pulses_per_second * dt)
                    self.frequencies[channel] = int(pulses_per_second)
                else:
                    self.frequencies[channel] = 0

                # Записуємо лічильник у Input Registers (FC04)
                # Канал n → адреса 16 + n*2 (Low word), 16 + n*2 + 1 (High word)
                counter_low = self.counters[channel] & 0xFFFF
                counter_high = (self.counters[channel] >> 16) & 0xFFFF
                store.setValues(4, 16 + channel * 2, [counter_low, counter_high])

                # Записуємо частоту у Input Registers (FC04)
                # Канал n (як frequency) → адреса 24 + n*2 (Low word), 24 + n*2 + 1 (High word)
                freq_low = self.frequencies[channel] & 0xFFFF
                freq_high = (self.frequencies[channel] >> 16) & 0xFFFF
                store.setValues(4, 24 + channel * 2, [freq_low, freq_high])

            time.sleep(0.1)

    def run(self):
        """Запуск Modbus TCP сервера"""
        _logger.info(f"Запуск симулятора ET-7284 на порту {self.port}, Unit ID: {self.unit_id}, PPM: {self.ppm}")

        update_thread = threading.Thread(target=self.update_counter_values, daemon=True)
        update_thread.start()

        StartTcpServer(
            context=self.context,
            address=("0.0.0.0", self.port),
            framer="socket",
        )


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 502
    unit_id = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    ppm = int(sys.argv[3]) if len(sys.argv) > 3 else 1000

    simulator = ET7284Simulator(port=port, unit_id=unit_id, ppm=ppm)
    simulator.run()
