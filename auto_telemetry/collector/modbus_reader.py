import logging
import time

from pymodbus.client import ModbusTcpClient

logger = logging.getLogger(__name__)

# ET-7017: FC04 (Read Input Registers), адреси 0–7 (ADR-002)
_ET7017_ADDR = 0
_ET7017_COUNT = 8

# ET-7284: FC04 (Read Input Registers), адреси 16–31, 8 каналів × 2 реєстри (ADR-002)
_ET7284_ADDR = 16
_ET7284_COUNT = 16


class ModbusModule:
    """Modbus TCP клієнт для одного модуля з автоматичним перепідключенням."""

    def __init__(self, name: str, ip: str, port: int,
                 unit_id: int, timeout: float, reconnect_delay: float):
        self.name = name
        self._unit_id = unit_id
        self._reconnect_delay = reconnect_delay
        self._client = ModbusTcpClient(host=ip, port=port, timeout=timeout)
        self._connected = False
        self._last_fail_at = 0.0

    def _try_connect(self) -> bool:
        if time.monotonic() - self._last_fail_at < self._reconnect_delay:
            return False
        try:
            self._connected = self._client.connect()
        except Exception as e:
            logger.warning('%s: connect error: %s', self.name, e)
            self._connected = False
        if self._connected:
            logger.info('%s: connected', self.name)
        else:
            self._last_fail_at = time.monotonic()
            logger.warning('%s: connection failed', self.name)
        return self._connected

    def _on_error(self, exc: Exception) -> None:
        logger.error('%s: read error: %s', self.name, exc)
        try:
            self._client.close()
        except Exception:
            pass
        self._connected = False
        self._last_fail_at = time.monotonic()

    def read_et7017(self) -> list[int] | None:
        """FC04, адреси 0–7. Повертає 8 uint16 або None при помилці."""
        if not self._connected and not self._try_connect():
            return None
        try:
            result = self._client.read_input_registers(
                _ET7017_ADDR, count=_ET7017_COUNT, device_id=self._unit_id)
            if result.isError():
                raise OSError(result)
            return list(result.registers)
        except Exception as e:
            self._on_error(e)
            return None

    def read_et7284(self) -> list[int] | None:
        """FC04, адреси 16–31. Повертає 16 uint16 (8 каналів × 2 слова) або None при помилці."""
        if not self._connected and not self._try_connect():
            return None
        try:
            result = self._client.read_input_registers(
                _ET7284_ADDR, count=_ET7284_COUNT, device_id=self._unit_id)
            if result.isError():
                raise OSError(result)
            return list(result.registers)
        except Exception as e:
            self._on_error(e)
            return None


def decode_et7017(registers: list[int] | None, channel_index: int) -> int | None:
    """
    Signed int16 значення каналу channel_index з регістрів ET-7017.
    pymodbus повертає uint16 → конвертуємо в int16.
    """
    if registers is None or channel_index >= len(registers):
        return None
    v = registers[channel_index]
    return v - 65536 if v > 32767 else v


def decode_et7284(registers: list[int] | None, channel_index: int) -> int | None:
    """
    uint32 значення каналу channel_index з регістрів ET-7284 (ADR-002).
    Registers[0..15] відповідають адресам 16..31.
    Канал n: Low word = registers[n*2], High word = registers[n*2+1].
    """
    if registers is None:
        return None
    lo = registers[channel_index * 2]
    hi = registers[channel_index * 2 + 1]
    return (hi << 16) | lo
