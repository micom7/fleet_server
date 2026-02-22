# auto_fleet — монорепо

Система телеметрії автопарку (~10 авто).

## Структура

```
auto_fleet/
├── DATA_CONTRACT.md     ← спільний контракт синхронізації (джерело правди)
├── fleet_server/        ← серверна частина (VPS)
│   └── README.md
└── auto_telemetry/      ← бортове ПЗ (RUTX11 на кожному авто)
    └── README.md
```

## Документація

| Файл | Призначення |
|---|---|
| [DATA_CONTRACT.md](DATA_CONTRACT.md) | HTTP API між авто і сервером: ендпоінти, формати, логіка sync |
| [fleet_server/](fleet_server/) | Серверна частина: FastAPI, Sync Service, PostgreSQL, Web UI |
| [auto_telemetry/](auto_telemetry/) | Бортове ПЗ: Collector, Outbound API, Portal, Agent |

