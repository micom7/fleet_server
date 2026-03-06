# Release Checklist

## Безпека

| # | Пункт | Статус | Коміт/PR |
|---|-------|--------|----------|
| S1 | `secure=True` на всіх cookies | ✅ Done | — |
| S2 | Валідація обов'язкових env vars при старті | ✅ Done | — |
| S3 | Cleanup job для `revoked_tokens` | ✅ Done | — |
| S4 | CORS → конкретний домен | 🔜 Last | — |
        (зміна займе 2 хвилини в main.py:
        allow_origins=["https://autotelemetry.duckdns.org"])

| # | Пункт | Статус | Коміт/PR |
|---|-------|--------|----------|
| R1 | Автоматичне створення партицій вимірювань | ✅ Done | — |
| R2 | Cleanup старих записів `sync_journal` | ✅ Done | — |

## Спостережуваність

| # | Пункт | Статус | Коміт/PR |
|---|-------|--------|----------|
| O1 | Request logging middleware в API | ✅ Done | — |

## Тести

| # | Пункт | Статус | Коміт/PR |
|---|-------|--------|----------|
| T1 | Smoke tests: auth (login/logout/refresh) | ✅ Done | — |
| T2 | Smoke tests: RLS (owner не бачить чужі авто) | ✅ Done | — |
| T3 | Smoke tests: sync cycle | ✅ Done | — |

## Операційне

| # | Пункт | Статус | Коміт/PR |
|---|-------|--------|----------|
| P1 | Документація backup/restore | ✅ Done | — |

---

**Статуси:** ✅ Done · 🔄 In Progress · ⬜ Todo · 🔜 Відкладено · ❌ Blocked
