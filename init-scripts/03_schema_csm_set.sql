\c db_csm_set

-- Equity curve: daily NAV per strategy (TimescaleDB hypertable)
CREATE TABLE IF NOT EXISTS equity_curve (
    time        TIMESTAMPTZ NOT NULL,
    strategy_id TEXT        NOT NULL,
    equity      DOUBLE PRECISION NOT NULL
);
SELECT create_hypertable('equity_curve', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_equity_curve_strategy_time
    ON equity_curve (strategy_id, time DESC);

-- Trade history: every trade record
CREATE TABLE IF NOT EXISTS trade_history (
    id          SERIAL      PRIMARY KEY,
    time        TIMESTAMPTZ NOT NULL,
    strategy_id TEXT        NOT NULL,
    symbol      TEXT        NOT NULL,
    side        TEXT        NOT NULL,
    quantity    DOUBLE PRECISION NOT NULL,
    price       DOUBLE PRECISION NOT NULL,
    commission  DOUBLE PRECISION DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_trade_history_strategy_time
    ON trade_history (strategy_id, time DESC);

-- Backtest log: metadata for each backtest run
CREATE TABLE IF NOT EXISTS backtest_log (
    id          SERIAL      PRIMARY KEY,
    run_id      TEXT        UNIQUE NOT NULL,
    strategy_id TEXT        NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    config      JSONB,
    summary     JSONB
);
