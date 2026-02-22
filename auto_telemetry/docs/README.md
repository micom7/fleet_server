# auto_telemetry — документація

## Архітектурні рішення (ADR)

| Файл | Опис |
|---|---|
| [ADR-001-listener-interaction.md](ADR-001-listener-interaction.md) | Взаємодія Collector → Monitor → Portal через ZeroMQ PUB/SUB: формат повідомлень, in-memory стан Portal, обробка помилок |
| [ADR-002-collector-modbus-spec.md](ADR-002-collector-modbus-spec.md) | Collector Modbus Reader: карта регістрів ET-7017/ET-7284, raw value scale, конвенція `channel_config`, поведінка при збоях |

## Специфікації обладнання (PDF)

| Файл | Пристрій |
|---|---|
| [et7017_register_table.pdf](et7017_register_table.pdf) | ICP DAS ET-7017 — аналогові входи 4–20 мА (8 каналів) |
| [et7284_register_table.pdf](et7284_register_table.pdf) | ICP DAS ET-7284 — лічильник / частота / енкодер |

## Плани розробки (майбутній функціонал)

| Файл | Опис |
|---|---|
| [plans/license_protection_plan.md](plans/license_protection_plan.md) | RSA-підписана прив'язка ПЗ до конкретного ПК |
| [plans/update_system_plan.md](plans/update_system_plan.md) | Система дистанційного оновлення та синхронізації (server-initiated) |
