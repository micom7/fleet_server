import json
import zmq


class Publisher:
    """ZeroMQ PUB: публікує пакети даних для Monitor та Portal (ADR-001)."""

    def __init__(self, address: str):
        ctx = zmq.Context.instance()
        self._sock = ctx.socket(zmq.PUB)
        self._sock.bind(address)

    def publish(self, cycle_time_iso: str, readings: list[dict]) -> None:
        """
        Формат (ADR-001):
          topic:   b'data'
          payload: {"cycle_time": "...", "readings": [{"channel_id": N, "value": F|null}, ...]}
        """
        payload = json.dumps({
            'cycle_time': cycle_time_iso,
            'readings': readings,
        }).encode()
        self._sock.send_multipart([b'data', payload])
