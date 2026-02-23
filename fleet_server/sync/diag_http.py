"""
Діагностика: чи працює httpx + anyio.run() на цьому ПК.
Запуск: cd fleet_server/sync && python diag_http.py
"""
import asyncio
import sys

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import anyio
import httpx

API_KEY = "dev_outbound_key_change_in_production"
URL     = "http://127.0.0.1:8001"

async def step(n: str, coro):
    try:
        await coro
        print(f"  [{n}] OK")
    except Exception as e:
        print(f"  [{n}] FAIL  {type(e).__name__}: {e}")


async def main():
    print("=== Diagnostics TCP/HTTP -> 127.0.0.1:8001 ===\n")

    # 1. Пряме TCP-з'єднання через anyio
    async def t1():
        s = await anyio.connect_tcp('127.0.0.1', 8001)
        await s.aclose()

    await step("1  anyio.connect_tcp direct  ", t1())

    # 2. httpx один запит у anyio-контексті
    async def t2():
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f'{URL}/status', headers={'X-API-Key': API_KEY})
            print(f"       status={r.status_code}, body={r.text[:80]}")

    await step("2  httpx.get in anyio ctx    ", t2())

    # 3. asyncio.to_thread (симуляція DB запиту)
    async def t3():
        import time
        await asyncio.to_thread(lambda: time.sleep(0.05))

    await step("3  asyncio.to_thread         ", t3())

    # 4. httpx ПІСЛЯ asyncio.to_thread
    async def t4():
        import time
        await asyncio.to_thread(lambda: time.sleep(0.05))
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f'{URL}/status', headers={'X-API-Key': API_KEY})
            print(f"       status={r.status_code}")

    await step("4  httpx after to_thread     ", t4())

    # 5. Два паралельних httpx-запити через anyio TaskGroup
    async def t5():
        async def one(label):
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f'{URL}/status', headers={'X-API-Key': API_KEY})
                print(f"       [{label}] status={r.status_code}")

        async with anyio.create_task_group() as tg:
            tg.start_soon(one, "task-a")
            tg.start_soon(one, "task-b")

    await step("5  two httpx in TaskGroup    ", t5())

    print("\nГотово.")


if __name__ == '__main__':
    anyio.run(main)
