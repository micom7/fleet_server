import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / '.env')


def _parse_config_txt(path: Path) -> dict[str, str]:
    result = {}
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '#' in line:
                line = line[:line.index('#')].strip()
            if '=' in line:
                k, _, v = line.partition('=')
                result[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return result


_cfg = _parse_config_txt(_ROOT / 'config.txt')


def _c(key: str, default: str = '') -> str:
    """config.txt → env → default."""
    return _cfg.get(key, os.getenv(key, default))


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    zmq_pub_address: str  # Collector BIND до цього адресу

    et7017_1_ip: str
    et7017_1_port: int
    et7017_1_unit_id: int

    et7017_2_ip: str
    et7017_2_port: int
    et7017_2_unit_id: int

    et7284_ip: str
    et7284_port: int
    et7284_unit_id: int

    polling_hz: float
    modbus_timeout: float
    reconnect_delay: float

    @property
    def dsn(self) -> str:
        return (f'host={self.db_host} port={self.db_port} '
                f'dbname={self.db_name} user={self.db_user} '
                f'password={self.db_password}')


def load_settings() -> Settings:
    return Settings(
        db_host=os.getenv('DB_HOST', 'localhost'),
        db_port=int(os.getenv('DB_PORT', '5432')),
        db_name=os.getenv('DB_NAME', 'telemetry'),
        db_user=os.getenv('DB_USER', 'telemetry'),
        db_password=os.getenv('DB_PASSWORD', ''),
        zmq_pub_address=os.getenv('ZMQ_COLLECTOR_PUB', 'tcp://127.0.0.1:5555'),
        et7017_1_ip=_c('MODBUS_ET7017_1_IP', 'localhost'),
        et7017_1_port=int(_c('MODBUS_ET7017_1_PORT', '5020')),
        et7017_1_unit_id=int(_c('MODBUS_ET7017_1_UNIT_ID', '1')),
        et7017_2_ip=_c('MODBUS_ET7017_2_IP', 'localhost'),
        et7017_2_port=int(_c('MODBUS_ET7017_2_PORT', '5021')),
        et7017_2_unit_id=int(_c('MODBUS_ET7017_2_UNIT_ID', '1')),
        et7284_ip=_c('MODBUS_ET7284_IP', 'localhost'),
        et7284_port=int(_c('MODBUS_ET7284_PORT', '5022')),
        et7284_unit_id=int(_c('MODBUS_ET7284_UNIT_ID', '1')),
        polling_hz=float(_c('POLLING_FREQUENCY_HZ', '1.0')),
        modbus_timeout=float(_c('MODBUS_TIMEOUT_SEC', '2.0')),
        reconnect_delay=float(_c('RECONNECT_DELAY_SEC', '5.0')),
    )
