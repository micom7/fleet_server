-- Fleet Server — центральна схема БД
-- PostgreSQL 16

-- ────────────────────────────────────────────────────────────────────
-- Розширення
-- ────────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()


-- ────────────────────────────────────────────────────────────────────
-- USERS
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE users (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT        NOT NULL UNIQUE,
    password_hash TEXT,                        -- NULL якщо тільки Google OAuth
    role          TEXT        NOT NULL DEFAULT 'owner'
                              CHECK (role IN ('superuser', 'owner')),
    status        TEXT        NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending', 'active', 'blocked')),
    full_name     TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_users_email  ON users (email);
CREATE INDEX idx_users_status ON users (status);

-- ────────────────────────────────────────────────────────────────────
-- OAUTH ACCOUNTS (Google)
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE oauth_accounts (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    provider     TEXT        NOT NULL DEFAULT 'google',
    provider_uid TEXT        NOT NULL,          -- Google sub
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_uid)
);

CREATE INDEX idx_oauth_user_id ON oauth_accounts (user_id);

-- ────────────────────────────────────────────────────────────────────
-- REVOKED TOKENS  (JWT анульовані при блокуванні)
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE revoked_tokens (
    jti        TEXT        PRIMARY KEY,         -- JWT ID (jti claim)
    user_id    UUID        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- автоматичне чищення прострочених токенів (через pg_cron або при запиті)
CREATE INDEX idx_revoked_tokens_expires ON revoked_tokens (expires_at);

-- ────────────────────────────────────────────────────────────────────
-- VEHICLES
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE vehicles (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT        NOT NULL,
    vpn_ip           INET        NOT NULL UNIQUE,   -- 10.0.0.11 .. 10.0.0.20
    api_port         INTEGER     NOT NULL DEFAULT 8001,  -- Outbound API порт на машині
    api_key          TEXT,                              -- per-vehicle ключ; NULL → VEHICLE_DEFAULT_API_KEY
    last_seen_at     TIMESTAMPTZ,
    last_sync_at     TIMESTAMPTZ,                       -- час останнього успішного sync (для gap-filling)
    sync_status      TEXT        NOT NULL DEFAULT 'unknown'
                                 CHECK (sync_status IN ('ok', 'timeout', 'error', 'unknown')),
    software_version TEXT,                              -- версія ПЗ з /status (для відстеження оновлень)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ────────────────────────────────────────────────────────────────────
-- VEHICLE ACCESS  (many-to-many: user ↔ vehicle)
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE vehicle_access (
    user_id    UUID NOT NULL REFERENCES users    (id) ON DELETE CASCADE,
    vehicle_id UUID NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, vehicle_id)
);

CREATE INDEX idx_vehicle_access_vehicle ON vehicle_access (vehicle_id);

-- ────────────────────────────────────────────────────────────────────
-- CHANNEL CONFIG  (конфігурація каналів, копія з авто)
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE channel_config (
    id          UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    vehicle_id  UUID    NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    channel_id  INTEGER NOT NULL,               -- ID каналу на авто
    name        TEXT    NOT NULL,
    unit        TEXT,
    min_value   DOUBLE PRECISION,
    max_value   DOUBLE PRECISION,
    synced_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vehicle_id, channel_id)
);

CREATE INDEX idx_channel_config_vehicle ON channel_config (vehicle_id);

-- ────────────────────────────────────────────────────────────────────
-- MEASUREMENTS  (партиціювання по місяцях)
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE measurements (
    id         BIGSERIAL,
    vehicle_id UUID             NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    channel_id INTEGER          NOT NULL,
    value      DOUBLE PRECISION NOT NULL,
    time       TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (id, time)
) PARTITION BY RANGE (time);

-- UNIQUE включає partition key (time) — вимога PostgreSQL для партиціонованих таблиць
-- Використовується Sync Service: INSERT ... ON CONFLICT (vehicle_id, channel_id, time) DO NOTHING
CREATE UNIQUE INDEX idx_measurements_unique
    ON measurements (vehicle_id, channel_id, time);

CREATE INDEX idx_measurements_lookup
    ON measurements (vehicle_id, channel_id, time DESC);

-- Початкові партиції — поточний та наступний місяць
-- При деплої скрипт повинен створювати партиції наперед
DO $$
DECLARE
    cur_month  DATE := date_trunc('month', now())::DATE;
    next_month DATE := (date_trunc('month', now()) + INTERVAL '1 month')::DATE;
    m2         DATE := (date_trunc('month', now()) + INTERVAL '2 months')::DATE;
BEGIN
    EXECUTE format(
        'CREATE TABLE measurements_%s PARTITION OF measurements
         FOR VALUES FROM (%L) TO (%L)',
        to_char(cur_month, 'YYYY_MM'), cur_month, next_month
    );
    EXECUTE format(
        'CREATE TABLE measurements_%s PARTITION OF measurements
         FOR VALUES FROM (%L) TO (%L)',
        to_char(next_month, 'YYYY_MM'), next_month, m2
    );
END $$;

-- ────────────────────────────────────────────────────────────────────
-- ALARMS LOG
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE alarms_log (
    id          BIGSERIAL   PRIMARY KEY,
    vehicle_id  UUID        NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    alarm_id    BIGINT      NOT NULL,            -- ID тривоги на авто (BIGSERIAL на машині → BIGINT тут)
    channel_id  INTEGER,
    severity    TEXT,
    message     TEXT        NOT NULL,
    triggered_at TIMESTAMPTZ NOT NULL,
    resolved_at  TIMESTAMPTZ,
    synced_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_alarms_vehicle_alarm_unique
    ON alarms_log (vehicle_id, alarm_id);         -- для ON CONFLICT при upsert resolved_at
CREATE INDEX idx_alarms_vehicle_time
    ON alarms_log (vehicle_id, triggered_at DESC);
CREATE INDEX idx_alarms_active
    ON alarms_log (vehicle_id) WHERE resolved_at IS NULL;

-- ────────────────────────────────────────────────────────────────────
-- SYNC JOURNAL  (зберігається 30 днів)
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE sync_journal (
    id          BIGSERIAL   PRIMARY KEY,
    vehicle_id  UUID        NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status      TEXT        NOT NULL CHECK (status IN ('ok', 'timeout', 'error')),
    rows_written INTEGER     NOT NULL DEFAULT 0,
    error_msg   TEXT
);

CREATE INDEX idx_sync_journal_vehicle_time
    ON sync_journal (vehicle_id, started_at DESC);

-- ────────────────────────────────────────────────────────────────────
-- ROW LEVEL SECURITY
-- ────────────────────────────────────────────────────────────────────

-- vehicles: owner бачить тільки свої; superuser — всі
-- FORCE потрібен бо fleet_app є власником таблиць
ALTER TABLE vehicles ENABLE ROW LEVEL SECURITY;
ALTER TABLE vehicles FORCE ROW LEVEL SECURITY;

CREATE POLICY vehicles_superuser ON vehicles
    USING (current_setting('app.user_role', true) = 'superuser');

CREATE POLICY vehicles_owner ON vehicles
    USING (
        current_setting('app.user_role', true) = 'owner'
        AND id IN (
            SELECT vehicle_id FROM vehicle_access
            WHERE user_id = NULLIF(current_setting('app.user_id', true), '')::UUID
        )
    );

-- measurements: через vehicle_id
ALTER TABLE measurements ENABLE ROW LEVEL SECURITY;
ALTER TABLE measurements FORCE ROW LEVEL SECURITY;

CREATE POLICY measurements_superuser ON measurements
    USING (current_setting('app.user_role', true) = 'superuser');

CREATE POLICY measurements_owner ON measurements
    USING (
        current_setting('app.user_role', true) = 'owner'
        AND vehicle_id IN (
            SELECT vehicle_id FROM vehicle_access
            WHERE user_id = NULLIF(current_setting('app.user_id', true), '')::UUID
        )
    );

-- alarms_log: аналогічно
ALTER TABLE alarms_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE alarms_log FORCE ROW LEVEL SECURITY;

CREATE POLICY alarms_superuser ON alarms_log
    USING (current_setting('app.user_role', true) = 'superuser');

CREATE POLICY alarms_owner ON alarms_log
    USING (
        current_setting('app.user_role', true) = 'owner'
        AND vehicle_id IN (
            SELECT vehicle_id FROM vehicle_access
            WHERE user_id = NULLIF(current_setting('app.user_id', true), '')::UUID
        )
    );

-- ────────────────────────────────────────────────────────────────────
-- GRANTS  (fleet_app — єдиний користувач додатку)
-- ────────────────────────────────────────────────────────────────────
-- fleet_app не має бути superuser / bypassrls — RLS повинен працювати
ALTER ROLE fleet_app NOSUPERUSER NOBYPASSRLS;

GRANT USAGE ON SCHEMA public TO fleet_app;
GRANT ALL ON ALL TABLES    IN SCHEMA public TO fleet_app;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO fleet_app;
-- для майбутніх таблиць/партицій
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES    TO fleet_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON SEQUENCES TO fleet_app;

-- ────────────────────────────────────────────────────────────────────
-- SUPERUSER за замовчуванням  (змінити email після деплою)
-- ────────────────────────────────────────────────────────────────────
-- Пароль встановити через API після першого запуску
INSERT INTO users (email, role, status, full_name)
VALUES ('admin@example.com', 'superuser', 'active', 'Fleet Admin');

-- ────────────────────────────────────────────────────────────────────
-- DEMO USER + VEHICLE  (виконати через seed_demo.py)
-- ────────────────────────────────────────────────────────────────────
-- INSERT INTO users (email, role, status, full_name)
-- VALUES ('demo@example.com', 'owner', 'active', 'Demo User');
--
-- INSERT INTO vehicles (name, vpn_ip, api_port)
-- VALUES ('Demo Vehicle', '10.0.0.99', 8001);
--
-- INSERT INTO vehicle_access (user_id, vehicle_id)
-- SELECT u.id, v.id
-- FROM users u, vehicles v
-- WHERE u.email = 'demo@example.com'
--   AND v.name  = 'Demo Vehicle';
