"""
Collector — сервіс збору даних.

Опитування ICP DAS модулів (1 Гц), нормалізація сигналів,
запис у PostgreSQL, публікація через ZeroMQ PUB.

Запуск: python collector/main.py
"""

import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

# Дозволяє запускати як скрипт: python collector/main.py
sys.path.insert(0, str(Path(__file__).parent))

import psycopg2

from db import ChannelConfig, ConfigListener, batch_insert, load_channel_configs
from modbus_reader import ModbusModule, decode_et7017, decode_et7284
from normalizer import normalize
from publisher import Publisher
from settings import Settings, load_settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(name)s: %(message)s',
)
logger = logging.getLogger('collector')


# ── Допоміжні функції ──────────────────────────────────────────────────────────

def _extract_raw(cfg: ChannelConfig,
                 r1: list[int] | None,
                 r2: list[int] | None,
                 r3: list[int] | None) -> int | float | None:
    """Повертає сире значення каналу з відповідного набору регістрів."""
    if cfg.module == 'et7017_1':
        return decode_et7017(r1, cfg.channel_index)
    if cfg.module == 'et7017_2':
        return decode_et7017(r2, cfg.channel_index)
    if cfg.module == 'et7284':
        return decode_et7284(r3, cfg.channel_index)
    logger.error('Невідомий модуль: %s (channel_id=%d)', cfg.module, cfg.channel_id)
    return None


def _connect_db(dsn: str):
    """Підключитися до БД з ретраями. Повертає з'єднання або None."""
    for attempt in range(1, 6):
        try:
            conn = psycopg2.connect(dsn)
            logger.info('DB підключено')
            return conn
        except Exception as e:
            logger.error('DB підключення #%d: %s', attempt, e)
            time.sleep(5)
    logger.critical('DB недоступна — продовжую без запису в БД')
    return None


# ── Головна функція ────────────────────────────────────────────────────────────

def main():
    s: Settings = load_settings()

    # ── БД ──────────────────────────────────────────────────────────────────
    db_conn = _connect_db(s.dsn)
    if db_conn is None:
        logger.critical('Неможливо стартувати без БД (потрібна channel_config)')
        sys.exit(1)

    configs: list[ChannelConfig] = load_channel_configs(db_conn)
    if not configs:
        logger.warning('channel_config порожня — жодного каналу не завантажено')
    else:
        logger.info('Завантажено %d каналів', len(configs))

    configs_lock = threading.Lock()

    def reload_configs():
        nonlocal configs
        try:
            with psycopg2.connect(s.dsn) as c:
                new = load_channel_configs(c)
            with configs_lock:
                configs = new
            logger.info('Конфіги перезавантажено: %d каналів', len(new))
        except Exception as e:
            logger.error('Перезавантаження конфігів не вдалося: %s', e)

    ConfigListener(s.dsn, reload_configs).start()

    # ── ZeroMQ ──────────────────────────────────────────────────────────────
    pub = Publisher(s.zmq_pub_address)
    logger.info('ZeroMQ PUB: bind %s', s.zmq_pub_address)

    # ── Modbus модулі ────────────────────────────────────────────────────────
    kw = dict(timeout=s.modbus_timeout, reconnect_delay=s.reconnect_delay)
    mod1 = ModbusModule('ET7017_1', s.et7017_1_ip, s.et7017_1_port, s.et7017_1_unit_id, **kw)
    mod2 = ModbusModule('ET7017_2', s.et7017_2_ip, s.et7017_2_port, s.et7017_2_unit_id, **kw)
    mod3 = ModbusModule('ET7284',   s.et7284_ip,   s.et7284_port,   s.et7284_unit_id,   **kw)

    cycle_interval = 1.0 / s.polling_hz
    logger.info('Collector запущено: %.1f Гц', s.polling_hz)

    executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix='modbus')

    # ── Цикл опитування ──────────────────────────────────────────────────────
    while True:
        t0 = time.monotonic()
        cycle_time = datetime.now(timezone.utc)
        cycle_time_iso = cycle_time.isoformat(timespec='milliseconds').replace('+00:00', 'Z')

        # 1. Читання модулів (паралельно — timeout одного не блокує інші)
        f1 = executor.submit(mod1.read_et7017)
        f2 = executor.submit(mod2.read_et7017)
        f3 = executor.submit(mod3.read_et7284)
        r1 = f1.result()
        r2 = f2.result()
        r3 = f3.result()

        # 2. Нормалізація
        with configs_lock:
            snapshot = list(configs)

        readings: list[dict] = []
        for cfg in snapshot:
            raw = _extract_raw(cfg, r1, r2, r3)
            if raw is None:
                value = None
            else:
                try:
                    value = normalize(raw, cfg.raw_min, cfg.raw_max,
                                      cfg.phys_min, cfg.phys_max)
                except ZeroDivisionError:
                    logger.error('channel_id=%d: raw_min == raw_max, пропускаємо', cfg.channel_id)
                    value = None
            readings.append({'channel_id': cfg.channel_id, 'value': value})

        # 3. Запис у БД (best-effort)
        if db_conn is not None:
            try:
                batch_insert(db_conn, cycle_time, readings)
            except Exception as e:
                logger.critical('Запис у БД не вдався: %s', e)
                try:
                    db_conn.close()
                except Exception:
                    pass
                db_conn = None

        if db_conn is None:
            # Спроба перепідключення — без блокування циклу
            try:
                db_conn = psycopg2.connect(s.dsn)
                logger.info('DB перепідключено')
            except Exception as e:
                logger.error('DB перепідключення не вдалося: %s', e)

        # 4. Публікація в ZeroMQ (завжди, навіть при збої БД — ADR-002)
        pub.publish(cycle_time_iso, readings)

        # 5. Витримка до кінця циклу
        elapsed = time.monotonic() - t0
        sleep = cycle_interval - elapsed
        if sleep > 0:
            time.sleep(sleep)
        else:
            logger.warning('Цикл затримався на %.3f с', -sleep)


if __name__ == '__main__':
    main()
