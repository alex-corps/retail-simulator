-- 0004_simulation_runs.sql
-- One row per period run. Progress is days_done / days_total.
-- The last committed day is last_done_date: current_date is reserved in PostgreSQL.

CREATE TABLE simulation_runs (
    id BIGSERIAL PRIMARY KEY,
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    days_total INT NOT NULL,
    days_done INT NOT NULL DEFAULT 0,
    last_done_date DATE,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    seed BIGINT NOT NULL,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    CONSTRAINT simulation_runs_range_check CHECK (date_from <= date_to),
    CONSTRAINT simulation_runs_days_total_check CHECK (days_total > 0),
    CONSTRAINT simulation_runs_days_check CHECK (days_done BETWEEN 0 AND days_total),
    CONSTRAINT simulation_runs_status_check CHECK (
        status IN ('running', 'completed', 'failed')
    )
);

CREATE INDEX idx_simulation_runs_started_at ON simulation_runs (started_at DESC);
