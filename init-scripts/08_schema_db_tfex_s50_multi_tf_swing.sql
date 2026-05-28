-- ============================================================================
-- 08_schema_db_tfex_s50_multi_tf_swing.sql
-- ----------------------------------------------------------------------------
-- Provisions the strategy-owned Postgres database for the TFEX S50 multi-
-- timeframe swing-intraday strategy. Idempotent: safe to re-run.
--
-- Conventions diverge from 03_schema_csm_set.sql on purpose:
--   * Money columns are NUMERIC(18,4), not DOUBLE PRECISION, because the
--     ingestion contract uses Decimal-as-string on the wire and the umbrella
--     rule forbids float for monetary values (TFEX CLAUDE.md hard rule #2;
--     umbrella CLAUDE.md "Monetary values are Decimal at the gateway boundary;
--     never float"). The csm-set schema predates this rule and will be
--     migrated separately.
--   * Percentage / ratio columns are NUMERIC(8,4) fractional (e.g. -0.0460
--     for −4.6%).
--   * Every time-series table carries a UNIQUE natural key so the strategy's
--     write paths (and gateway re-ingestion) can use INSERT … ON CONFLICT for
--     idempotent re-posts.
-- ============================================================================

-- 1. Create the database conditionally (PostgreSQL has no CREATE DATABASE
--    IF NOT EXISTS; \gexec is the idiomatic guard used in 01_create_databases.sql).
SELECT 'CREATE DATABASE db_tfex_s50_multi_tf_swing'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'db_tfex_s50_multi_tf_swing'
)\gexec

\connect db_tfex_s50_multi_tf_swing

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------------
-- equity_curve — daily NAV per strategy (TimescaleDB hypertable).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS equity_curve (
    time        TIMESTAMPTZ    NOT NULL,
    strategy_id TEXT           NOT NULL,
    value       NUMERIC(18, 4) NOT NULL
);
SELECT create_hypertable('equity_curve', 'time', if_not_exists => TRUE);
CREATE UNIQUE INDEX IF NOT EXISTS uq_equity_curve_time_strategy
    ON equity_curve (time, strategy_id);
CREATE INDEX IF NOT EXISTS idx_equity_curve_strategy_time
    ON equity_curve (strategy_id, time DESC);

-- ---------------------------------------------------------------------------
-- trade_history — every executed (or simulated) trade for this strategy.
-- TFEX-specific: position is in CONTRACTS (integer), and margin_used is a
-- first-class column so risk / margin-usage reporting is queryable directly
-- without parsing extended_data JSONB.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trade_history (
    id          SERIAL         PRIMARY KEY,
    time        TIMESTAMPTZ    NOT NULL,
    strategy_id TEXT           NOT NULL,
    symbol      TEXT           NOT NULL,                                  -- e.g. 'S50Z26'
    side        TEXT           NOT NULL CHECK (side IN ('BUY', 'SELL')),
    contracts   INTEGER        NOT NULL,
    price       NUMERIC(18, 4) NOT NULL,
    margin_used NUMERIC(18, 4) NOT NULL,
    commission  NUMERIC(18, 4) NOT NULL DEFAULT 0,
    pnl         NUMERIC(18, 4)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_trade_history_dedup
    ON trade_history (strategy_id, time, symbol, side);
CREATE INDEX IF NOT EXISTS idx_trade_history_strategy_time
    ON trade_history (strategy_id, time DESC);

-- ---------------------------------------------------------------------------
-- backtest_log — one row per walk-forward backtest run.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backtest_log (
    id          SERIAL      PRIMARY KEY,
    run_id      TEXT        UNIQUE NOT NULL,
    strategy_id TEXT        NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    config      JSONB,
    summary     JSONB
);
CREATE INDEX IF NOT EXISTS idx_backtest_log_strategy_started
    ON backtest_log (strategy_id, started_at DESC);

-- ---------------------------------------------------------------------------
-- benchmark_equity_curve — derivatives-native benchmark (S50 underlying or
-- SET50 TR) used for risk-adjusted performance attribution.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS benchmark_equity_curve (
    time      TIMESTAMPTZ    NOT NULL,
    benchmark TEXT           NOT NULL,
    value     NUMERIC(18, 4) NOT NULL
);
SELECT create_hypertable('benchmark_equity_curve', 'time', if_not_exists => TRUE);
CREATE UNIQUE INDEX IF NOT EXISTS uq_benchmark_equity_curve_time_benchmark
    ON benchmark_equity_curve (time, benchmark);
CREATE INDEX IF NOT EXISTS idx_benchmark_equity_curve_benchmark_time
    ON benchmark_equity_curve (benchmark, time DESC);
