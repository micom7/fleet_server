import logging
import select
import threading
import time
from dataclasses import dataclass
from datetime import datetime

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChannelConfig:
    channel_id: int
    module: str         # 'et7017_1' | 'et7017_2' | 'et7284'
    channel_index: int  # 0-based індекс каналу на модулі
    signal_type: str    # 'analog_420' | 'encoder_counter' | 'encoder_frequency' | ...
    raw_min: float
    raw_max: float
    phys_min: float
    phys_max: float


def load_channel_configs(conn) -> list[ChannelConfig]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT channel_id, module, channel_index, signal_type,
                   raw_min, raw_max, phys_min, phys_max
            FROM channel_config
            WHERE enabled = TRUE
            ORDER BY channel_id
        """)
        return [ChannelConfig(*row) for row in cur.fetchall()]


def batch_insert(conn, cycle_time: datetime, readings: list[dict]) -> None:
    """Батч-інсерт усіх вимірювань циклу в одній транзакції."""
    if not readings:
        return
    rows = [(cycle_time, r['channel_id'], r['value']) for r in readings]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            'INSERT INTO measurements (time, channel_id, value) VALUES %s',
            rows,
        )
    conn.commit()


class ConfigListener(threading.Thread):
    """
    Фоновий потік: LISTEN config_changed → on_change().
    При розриві з'єднання автоматично перепідключається.
    """

    def __init__(self, dsn: str, on_change):
        super().__init__(daemon=True, name='config-listener')
        self._dsn = dsn
        self._on_change = on_change

    def run(self):
        while True:
            try:
                conn = psycopg2.connect(self._dsn)
                conn.set_isolation_level(0)  # autocommit — обов'язково для LISTEN
                with conn.cursor() as cur:
                    cur.execute('LISTEN config_changed;')
                logger.info('ConfigListener: LISTEN config_changed')
                while True:
                    if select.select([conn], [], [], 5.0)[0]:
                        conn.poll()
                        while conn.notifies:
                            n = conn.notifies.pop()
                            logger.info('pg_notify config_changed: channel_id=%s', n.payload)
                            self._on_change()
            except Exception as e:
                logger.error('ConfigListener: %s — reconnect in 5s', e)
                time.sleep(5)
