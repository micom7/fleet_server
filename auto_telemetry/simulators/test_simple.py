"""Простий тест Modbus сервера"""
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusDeviceContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock

# Створюємо datastore з Input Registers
store = ModbusDeviceContext(
    ir=ModbusSequentialDataBlock(0, [16000]*8)  # 8 реєстрів починаючи з 0
)

context = ModbusServerContext(devices={1: store}, single=False)

print("Запуск Modbus TCP сервера на порту 5020...")
print("Device ID: 1")
print("Input Registers: адреси 0-7")

StartTcpServer(
    context=context,
    address=("0.0.0.0", 5020),
    framer="socket"
)
