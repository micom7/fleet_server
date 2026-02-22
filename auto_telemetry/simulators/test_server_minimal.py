"""Мінімальний тестовий Modbus сервер"""
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusDeviceContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock

# Створюємо простий datastore з Input Registers
store = ModbusDeviceContext(
    ir=ModbusSequentialDataBlock(0, [10000, 11000, 12000, 13000, 14000, 15000, 16000, 17000])
)

context = ModbusServerContext(devices={1: store}, single=False)

print("Запуск тестового Modbus TCP сервера на порту 5020...")
print("Input Registers: адреси 0-7")
print("Значення: 10000, 11000, 12000, 13000, 14000, 15000, 16000, 17000")

StartTcpServer(
    context=context,
    address=("0.0.0.0", 5020),
    framer="socket"
)
