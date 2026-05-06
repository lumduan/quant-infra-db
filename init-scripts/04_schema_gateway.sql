\c db_gateway

-- Daily performance: aggregated daily stats per strategy (TimescaleDB hypertable)
CREATE TABLE IF NOT EXISTS daily_performance (
    time            TIMESTAMPTZ NOT NULL,
    strategy_id     TEXT        NOT NULL,
    daily_return    DOUBLE PRECISION,
    cumulative_return DOUBLE PRECISION,
    total_value     DOUBLE PRECISION,
    cash_balance    DOUBLE PRECISION,
    max_drawdown    DOUBLE PRECISION,
    sharpe_ratio    DOUBLE PRECISION,
    metadata        JSONB
);
SELECT create_hypertable('daily_performance', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_daily_performance_strategy_time
    ON daily_performance (strategy_id, time DESC);

-- Portfolio snapshot: combined cross-strategy snapshot (TimescaleDB hypertable)
CREATE TABLE IF NOT EXISTS portfolio_snapshot (
    time              TIMESTAMPTZ NOT NULL,
    total_portfolio   DOUBLE PRECISION NOT NULL,
    weighted_return   DOUBLE PRECISION,
    combined_drawdown DOUBLE PRECISION,
    active_strategies INTEGER,
    allocation        JSONB
);
SELECT create_hypertable('portfolio_snapshot', 'time', if_not_exists => TRUE);
