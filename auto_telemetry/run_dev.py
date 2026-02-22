"""
Dev runner — запускає всі сервіси auto_telemetry в одному терміналі.

Запуск:
    python run_dev.py                  # все
    python run_dev.py --no-sims        # без симуляторів
    python run_dev.py --no-collector   # без колектора
    python run_dev.py --no-api         # без API
    python run_dev.py --outbound       # + Outbound API :8001 (для Fleet Server)
"""

import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).parent
SIM_DIR = ROOT / "simulators"
COLLECTOR_DIR = ROOT / "collector"
API_DIR = ROOT / "api"

# ANSI кольори для диференціації процесів
_C = {
    "sim1":      "\033[36m",    # cyan
    "sim2":      "\033[96m",    # bright cyan
    "sim3":      "\033[35m",    # magenta
    "collector": "\033[33m",    # yellow
    "api":       "\033[32m",    # green
    "outbound":  "\033[34m",    # blue
}
_RST  = "\033[0m"
_BOLD = "\033[1m"
_RED  = "\033[31m"
_GRN  = "\033[32m"
_YLW  = "\033[33m"


def _log(msg: str) -> None:
    print(f"{_GRN}[runner]{_RST} {msg}", flush=True)


def _warn(msg: str) -> None:
    print(f"{_YLW}[runner]{_RST} {msg}", flush=True)


def _err(msg: str) -> None:
    print(f"{_RED}[runner]{_RST} {msg}", flush=True)


def _stream(proc: subprocess.Popen, label: str) -> None:
    """Читає stdout процесу і виводить з кольоровим префіксом."""
    color = _C.get(label, "")
    prefix = f"{color}{_BOLD}[{label:>9}]{_RST} "
    for line in proc.stdout:
        sys.stdout.write(prefix + line)
        sys.stdout.flush()


def _start(args: list[str], label: str, cwd: Path) -> subprocess.Popen:
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(cwd),
        bufsize=1,
    )
    t = threading.Thread(target=_stream, args=(proc, label), daemon=True)
    t.start()
    return proc


def main() -> None:
    parser = argparse.ArgumentParser(description="Dev runner для auto_telemetry")
    parser.add_argument("--no-sims",      action="store_true", help="Не запускати симулятори")
    parser.add_argument("--no-collector", action="store_true", help="Не запускати колектор")
    parser.add_argument("--api",          action="store_true", help="Запустити API (uvicorn)")
    parser.add_argument("--api-port",     type=int, default=8100, help="Порт API (default: 8100)")
    parser.add_argument("--outbound",     action="store_true", help="Запустити Outbound API :8001 (для Fleet Server)")
    opts = parser.parse_args()

    py = sys.executable
    procs: list[tuple[str, subprocess.Popen]] = []

    # ── Симулятори ────────────────────────────────────────────────────────────
    if not opts.no_sims:
        procs.append(("sim1", _start(
            [py, "et7017_simulator.py", "5020", "1"],
            "sim1", SIM_DIR,
        )))
        time.sleep(0.3)
        procs.append(("sim2", _start(
            [py, "et7017_simulator.py", "5021", "1"],
            "sim2", SIM_DIR,
        )))
        time.sleep(0.3)
        procs.append(("sim3", _start(
            [py, "et7284_simulator.py", "5022", "1", "1000"],
            "sim3", SIM_DIR,
        )))
        time.sleep(0.5)
        _log("Симулятори: :5020 (ET7017-1) | :5021 (ET7017-2) | :5022 (ET7284)")

    # ── Колектор ──────────────────────────────────────────────────────────────
    if not opts.no_collector:
        procs.append(("collector", _start(
            [py, "main.py"],
            "collector", COLLECTOR_DIR,
        )))
        time.sleep(0.5)
        _log("Колектор запущено")

    # ── API (uvicorn) ─────────────────────────────────────────────────────────
    if opts.api:
        procs.append(("api", _start(
            [py, "-m", "uvicorn", "main:app",
             "--host", "127.0.0.1", "--port", str(opts.api_port)],
            "api", API_DIR,
        )))
        _log(f"API: http://127.0.0.1:{opts.api_port}")

    # ── Outbound API (Fleet Server pull) ──────────────────────────────────────
    if opts.outbound:
        procs.append(("outbound", _start(
            [py, "-m", "uvicorn", "outbound.main:app",
             "--host", "0.0.0.0", "--port", "8001"],
            "outbound", ROOT,
        )))
        _log("Outbound API: http://0.0.0.0:8001  (X-API-Key: див. .env OUTBOUND_API_KEY)")

    if not procs:
        _warn("Немає сервісів для запуску (всі вимкнені флагами).")
        return

    print()
    _log(f"Запущено {len(procs)} сервіс(ів). Ctrl+C для зупинки.\n")

    # ── Головний цикл (моніторинг) ────────────────────────────────────────────
    try:
        while True:
            time.sleep(2)
            for label, proc in procs:
                rc = proc.poll()
                if rc is not None:
                    _err(f"'{label}' завершився несподівано (код {rc})")
    except KeyboardInterrupt:
        print()
        _warn("Отримано Ctrl+C — зупиняємо всі процеси...")

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    for label, proc in procs:
        if proc.poll() is None:
            proc.terminate()

    deadline = time.monotonic() + 4.0
    for label, proc in procs:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            _warn(f"'{label}' не відповів на terminate — kill")
            proc.kill()

    _log("Всі процеси зупинені.")


if __name__ == "__main__":
    main()
