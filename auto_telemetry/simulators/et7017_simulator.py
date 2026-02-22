"""
Симулятор ICP DAS ET-7017
8-канальний аналоговий вхід (4-20 мА), 4 цифрові виходи
Modbus TCP сервер
"""

import random
import time
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusDeviceContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock
import logging

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger(__name__)


class ET7017Simulator:
    """
    Симулятор ET-7017: 8 аналогових входів (16-bit, 4-20 мА)
    Modbus Input Registers (function code 04):
    - Реєстри 0-7: AI канали 0-7 (16-bit значення)
    - Для 4-20 мА: значення від 6400 до 32000 (або 0-32767)
    """
    
    def __init__(self, port=502, unit_id=1):
        self.port = port
        self.unit_id = unit_id
        
        # Створюємо datastore для Input Registers (тільки читання)
        # 8 реєстрів для AI каналів (0-7)
        # Значення для 4-20 мА: 6400 (4 мА) до 32000 (20 мА)
        store = ModbusDeviceContext(
            di=ModbusSequentialDataBlock(0, [0]*4),  # Digital Inputs (не використовується)
            co=ModbusSequentialDataBlock(0, [0]*4),  # Digital Outputs (Coils)
            hr=ModbusSequentialDataBlock(0, [0]*8),  # Holding Registers (не використовується)
            ir=ModbusSequentialDataBlock(0, [16000]*9)  # +1 через off-by-one в pymodbus 3.12 verifyAddress
        )
        
        self.context = ModbusServerContext(devices={unit_id: store}, single=False)
        
        # Ідентифікація пристрою (опціонально, можна прибрати)
        self.identity = None
    
    def update_analog_values(self):
        """Оновлює значення аналогових входів (симуляція реальних датчиків)"""
        while True:
            store = self.context[self.unit_id]
            for channel in range(8):
                base_value = 16000  # ~12 мА (середина діапазону)
                noise = random.randint(-500, 500)
                value = max(6400, min(32000, base_value + noise))
                # FC=4 (Input Registers), pymodbus 3.12+
                store.setValues(4, channel, [value])
            time.sleep(0.1)
    
    def run(self):
        """Запуск Modbus TCP сервера"""
        _logger.info(f"Запуск симулятора ET-7017 на порту {self.port}, Unit ID: {self.unit_id}")
        
        # Запускаємо оновлення значень у фоновому потоці
        import threading
        update_thread = threading.Thread(target=self.update_analog_values, daemon=True)
        update_thread.start()
        
        # Запускаємо Modbus TCP сервер
        StartTcpServer(
            context=self.context,
            address=("0.0.0.0", self.port),
            framer="socket"  # TCP socket framer
        )


if __name__ == "__main__":
    import sys
    
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 502
    unit_id = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    
    simulator = ET7017Simulator(port=port, unit_id=unit_id)
    simulator.run()
