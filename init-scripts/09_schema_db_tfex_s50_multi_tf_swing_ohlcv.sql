-- ============================================================================
-- 09_schema_db_tfex_s50_multi_tf_swing_ohlcv.sql
-- ----------------------------------------------------------------------------
-- Adds OHLCV mirror tables to ``db_tfex_s50_multi_tf_swing`` for the TFEX S50
-- multi-timeframe swing strategy's Phase 1 data infrastructure.
--
-- The strategy stores raw and back-adjusted-continuous OHLCV in local Parquet
-- under ``data/`` as the source of truth. These TimescaleDB tables are a
-- queryable mirror written by the strategy's idempotent refresh path
-- (``src/tfex_s50_multi_tf_swing/data/db_writer.py``). OpenBB and other SQL
-- consumers read from here.
--
-- Conventions match 08_schema_db_tfex_s50_multi_tf_swing.sql:
--   * Money / price columns: NUMERIC(18, 4) (Decimal-on-wire; never float).
--   * Volume: NUMERIC(18, 4) (futures volumes are small integers in practice
--     but the column type stays consistent with price for arithmetic safety).
--   * Every table is a TimescaleDB hypertable on ``time``; chunks are 30-day
--     intervals (5-year backfill at 5m ≈ 87k rows/chunk → manageable).
--   * Every table carries a UNIQUE natural key so the strategy's writer can
--     use ``INSERT … ON CONFLICT … DO UPDATE`` for full idempotency.
--   * Fully idempotent: re-running this script (or the container init phase)
--     is a no-op.
-- ============================================================================

\connect db_tfex_s50_multi_tf_swing

-- ``timescaledb`` was already enabled by 08; the guard is cheap and keeps the
-- script self-contained if 08 is ever re-ordered.
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------------
-- ohlcv_raw — per-quarterly-contract OHLCV at 4H / 1H / 5m.
-- Source of truth lives in Parquet; this is the queryable mirror.
-- The ``contract`` column uses the TradingView per-contract symbol convention
-- (e.g. 'S50H2026', 'S50M2026') established in
-- src/tfex_s50_multi_tf_swing/data/contracts.py.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ohlcv_raw (
    time          TIMESTAMPTZ    NOT NULL,
    contract      TEXT           NOT NULL,
    timeframe     TEXT           NOT NULL CHECK (timeframe IN ('5m', '1h', '4h')),
    open          NUMERIC(18, 4) NOT NULL,
    high          NUMERIC(18, 4) NOT NULL,
    low           NUMERIC(18, 4) NOT NULL,
    close         NUMERIC(18, 4) NOT NULL,
    volume        NUMERIC(18, 4) NOT NULL DEFAULT 0,
    open_interest NUMERIC(18, 4)
);
SELECT create_hypertable(
    'ohlcv_raw',
    'time',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ohlcv_raw_time_contract_tf
    ON ohlcv_raw (time, contract, timeframe);
CREATE INDEX IF NOT EXISTS idx_ohlcv_raw_contract_tf_time
    ON ohlcv_raw (contract, timeframe, time DESC);

-- ---------------------------------------------------------------------------
-- ohlcv_continuous — back-adjusted continuous series at each timeframe.
-- Built locally from ohlcv_raw using a volume-crossover roll
-- (default ``roll_offset_days=5``). ``contract_at_time`` records which
-- quarterly contract was active at that bar; ``adjustment_factor`` is the
-- cumulative ratio applied to historical prices to remove rollover gaps.
-- TradingView's own ``S501!`` continuous is fetched separately and stored only
-- as a validation cross-check (Parquet only; it is NOT mirrored here).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ohlcv_continuous (
    time              TIMESTAMPTZ     NOT NULL,
    timeframe         TEXT            NOT NULL CHECK (timeframe IN ('5m', '1h', '4h')),
    open              NUMERIC(18, 4)  NOT NULL,
    high              NUMERIC(18, 4)  NOT NULL,
    low               NUMERIC(18, 4)  NOT NULL,
    close             NUMERIC(18, 4)  NOT NULL,
    volume            NUMERIC(18, 4)  NOT NULL DEFAULT 0,
    contract_at_time  TEXT            NOT NULL,
    adjustment_factor NUMERIC(18, 8)  NOT NULL DEFAULT 1
);
SELECT create_hypertable(
    'ohlcv_continuous',
    'time',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ohlcv_continuous_time_tf
    ON ohlcv_continuous (time, timeframe);
CREATE INDEX IF NOT EXISTS idx_ohlcv_continuous_tf_time
    ON ohlcv_continuous (timeframe, time DESC);
