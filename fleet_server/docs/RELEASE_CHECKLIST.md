# Release Checklist

## Безпека

| # | Пункт | Статус | Коміт/PR |
|---|-------|--------|----------|
| S1 | `secure=True` на всіх cookies | ✅ Done | — |
| S2 | Валідація обов'язкових env vars при старті | ⬜ Todo | — |
| S3 | Cleanup job для `revoked_tokens` | ⬜ Todo | — |
| S4 | CORS → конкретний домен | 🔜 Last | — |

## Надійність

| # | Пункт | Статус | Коміт/PR |
|---|-------|--------|----------|
| R1 | Автоматичне створення партицій вимірювань | ⬜ Todo | — |
| R2 | Cleanup старих записів `sync_journal` | ⬜ Todo | — |

## Спостережуваність

| # | Пункт | Статус | Коміт/PR |
|---|-------|--------|----------|
| O1 | Request logging middleware в API | ⬜ Todo | — |

## Тести

| # | Пункт | Статус | Коміт/PR |
|---|-------|--------|----------|
| T1 | Smoke tests: auth (login/logout/refresh) | ⬜ Todo | — |
| T2 | Smoke tests: RLS (owner не бачить чужі авто) | ⬜ Todo | — |
| T3 | Smoke tests: sync cycle | ⬜ Todo | — |

## Операційне

| # | Пункт | Статус | Коміт/PR |
|---|-------|--------|----------|
| P1 | Документація backup/restore | ⬜ Todo | — |

---

**Статуси:** ✅ Done · 🔄 In Progress · ⬜ Todo · 🔜 Відкладено · ❌ Blocked
