-- =============================================================================
-- 05_schema_strategy_report.sql
-- =============================================================================
-- Purpose: Strategies-Report-Metrics — Phase 2 schema additions (tables + indexes).
--   * db_csm_set:
--       - ALTER trade_history with per-trade P&L columns + relaxed side CHECK
--       - NEW hypertable benchmark_equity_curve (buy-and-hold benchmark NAV)
--   * db_gateway:
--       - NEW hypertable strategy_report_snapshot (JSONB report storage)
--
-- Order dependency: runs after 03/04. Continuous aggregates that read from
-- the new/altered tables live in 06_continuous_aggregates.sql so the source
-- hypertables exist before any view references them.
--
-- Idempotency: every statement uses IF NOT EXISTS / if_not_exists => TRUE
-- so the script is safe to re-run against an already-migrated cluster.
-- =============================================================================

\c db_csm_set

-- New per-trade P&L columns. Nullable for open trades and historical rows.
ALTER TABLE trade_history
    ADD COLUMN IF NOT EXISTS entry_price   NUMERIC(18,4),
    ADD COLUMN IF NOT EXISTS exit_price    NUMERIC(18,4),
    ADD COLUMN IF NOT EXISTS realized_pnl  NUMERIC(18,4),
    ADD COLUMN IF NOT EXISTS duration_bars INTEGER;

-- Relax side CHECK to accept the canonical csm-set set plus legacy values.
-- DROP is idempotent via IF EXISTS; the broader superset never rejects rows.
ALTER TABLE trade_history
    DROP CONSTRAINT IF EXISTS trade_history_side_check;
ALTER TABLE trade_history
    ADD CONSTRAINT trade_history_side_check
        CHECK (side IN ('LONG','SHORT','BUY','SELL','HOLD'));

-- Convert trade_history into a TimescaleDB hypertable so that
-- 06_continuous_aggregates.sql can build a monthly cagg over it.
-- Guarded so the block runs only on a non-hypertable: re-runs skip the work.
-- PRIMARY KEY must include the partitioning column (TimescaleDB requirement),
-- so the original SERIAL PK on `id` is widened to `(id, time)`.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM timescaledb_information.hypertables
        WHERE hypertable_name = 'trade_history'
    ) THEN
        ALTER TABLE trade_history DROP CONSTRAINT IF EXISTS trade_history_pkey;
        ALTER TABLE trade_history ADD CONSTRAINT trade_history_pkey PRIMARY KEY (id, time);
        PERFORM create_hypertable(
            'trade_history', 'time',
            migrate_data => TRUE,
            if_not_exists => TRUE
        );
    END IF;
END
$$;

-- Buy-and-hold benchmark equity per (strategy, symbol, day).
CREATE TABLE IF NOT EXISTS benchmark_equity_curve (
    time              TIMESTAMPTZ    NOT NULL,
    strategy_id       TEXT           NOT NULL,
    benchmark_symbol  TEXT           NOT NULL,
    equity            NUMERIC(18,4)  NOT NULL,
    UNIQUE (time, strategy_id, benchmark_symbol)
);
SELECT create_hypertable('benchmark_equity_curve', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_benchmark_strategy_time
    ON benchmark_equity_curve (strategy_id, time DESC);

\c db_gateway

-- JSONB report snapshot upserted by the gateway on each daily ingest.
CREATE TABLE IF NOT EXISTS strategy_report_snapshot (
    time         TIMESTAMPTZ NOT NULL,
    strategy_id  TEXT        NOT NULL,
    report       JSONB       NOT NULL,
    computed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (time, strategy_id)
);
SELECT create_hypertable('strategy_report_snapshot', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_strategy_report_strategy_time
    ON strategy_report_snapshot (strategy_id, time DESC);
