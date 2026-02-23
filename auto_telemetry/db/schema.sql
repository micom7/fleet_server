-- Auto Telemetry — схема БД
-- Запускається автоматично Docker postgres при першому старті
-- Передумова: БД 'telemetry' та юзер 'telemetry' вже створені через POSTGRES_USER/POSTGRES_DB env

CREATE TYPE signal_type AS ENUM (
    'analog_420',
    'voltage_010',
    'digital',
    'encoder_counter',
    'encoder_frequency'
);

CREATE TABLE channel_config (
    channel_id      SMALLINT PRIMARY KEY,
    module          VARCHAR(20) NOT NULL,
    channel_index   SMALLINT NOT NULL,
    signal_type     signal_type NOT NULL,
    name            VARCHAR(50) NOT NULL,
    unit            VARCHAR(20),
    raw_min         REAL NOT NULL,
    raw_max         REAL NOT NULL,
    phys_min        REAL NOT NULL,
    phys_max        REAL NOT NULL,
    enabled         BOOLEAN DEFAULT TRUE,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE channel_config_history (
    id          BIGSERIAL PRIMARY KEY,
    channel_id  SMALLINT NOT NULL,
    changed_at  TIMESTAMPTZ DEFAULT NOW(),
    changed_by  VARCHAR(50),
    old_config  JSONB NOT NULL,
    new_config  JSONB NOT NULL
);

CREATE OR REPLACE FUNCTION channel_config_on_update()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    INSERT INTO channel_config_history (channel_id, changed_by, old_config, new_config)
    VALUES (
        NEW.channel_id,
        current_user,
        row_to_json(OLD)::jsonb,
        row_to_json(NEW)::jsonb
    );
    PERFORM pg_notify('config_changed', NEW.channel_id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER channel_config_update_trigger
BEFORE UPDATE ON channel_config
FOR EACH ROW EXECUTE FUNCTION channel_config_on_update();

CREATE TABLE measurements (
    time        TIMESTAMPTZ NOT NULL,
    channel_id  SMALLINT NOT NULL REFERENCES channel_config(channel_id),
    value       DOUBLE PRECISION
);

CREATE INDEX ON measurements (channel_id, time DESC);
CREATE INDEX ON measurements (time DESC);

CREATE TABLE alarm_rules (
    id          BIGSERIAL PRIMARY KEY,
    channel_id  SMALLINT NOT NULL REFERENCES channel_config(channel_id),
    name        VARCHAR(100) NOT NULL,
    rule_type   VARCHAR(30) NOT NULL,
    threshold   DOUBLE PRECISION,
    gradient    DOUBLE PRECISION,
    window_sec  INTEGER,
    severity    VARCHAR(20) DEFAULT 'warning',
    enabled     BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE alarm_rules_history (
    id          BIGSERIAL PRIMARY KEY,
    rule_id     BIGINT NOT NULL,
    changed_at  TIMESTAMPTZ DEFAULT NOW(),
    changed_by  VARCHAR(50),
    old_config  JSONB NOT NULL,
    new_config  JSONB NOT NULL
);

CREATE OR REPLACE FUNCTION alarm_rules_on_update()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    INSERT INTO alarm_rules_history (rule_id, changed_by, old_config, new_config)
    VALUES (
        NEW.id,
        current_user,
        row_to_json(OLD)::jsonb,
        row_to_json(NEW)::jsonb
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER alarm_rules_update_trigger
BEFORE UPDATE ON alarm_rules
FOR EACH ROW EXECUTE FUNCTION alarm_rules_on_update();

CREATE TABLE alarms_log (
    id           BIGSERIAL PRIMARY KEY,
    rule_id      BIGINT REFERENCES alarm_rules(id),
    channel_id   SMALLINT NOT NULL,
    triggered_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at  TIMESTAMPTZ,
    value        DOUBLE PRECISION,
    message      TEXT
);

CREATE INDEX ON alarms_log (channel_id, triggered_at DESC);
CREATE INDEX ON alarms_log (resolved_at) WHERE resolved_at IS NULL;
