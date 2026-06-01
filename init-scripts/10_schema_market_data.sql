-- ============================================================================
-- 10_schema_market_data.sql
-- ----------------------------------------------------------------------------
-- Shared canonical OHLCV store for the Market Data engine
-- (feature-market-data-engine, Phase 1). Lives in its OWN database
-- ``db_market_data`` (created in 01_create_databases.sql), inside a
-- ``market_data`` schema, so the canonical store is independently owned and
-- decoupled from db_gateway / the strategy DBs (ADR decisions D4/D7).
--
-- The standalone ``quant-marketdata-engine`` service is the eventual sole
-- writer (Phase 2): it fetches once via tvkit and idempotently upserts raw bars
-- + corporate actions here. Strategies and OpenBB READ through the gateway
-- proxy; they never fetch tvkit and never write these tables.
--
-- Conventions:
--   * Price columns: NUMERIC(18, 6). This DELIBERATELY diverges from the
--     08/09 tfex mirror's NUMERIC(18, 4): this is a shared multi-asset store
--     and the ADR §5 read contract serialises 6-dp prices (e.g. "912.400000").
--     The 08/09 mirror is being retired (ADR §7), so matching it is not a
--     constraint. (Money is always Decimal-on-wire; never float.)
--   * Volume / open_interest: NUMERIC(20, 4). ``open_interest`` is carried from
--     day one (futures only; NULL for equities) — adding it later means a
--     backfill (D10).
--   * ``ts`` is the BAR-OPEN time, stored UTC (display Asia/Bangkok at the edge).
--   * Store RAW/unadjusted bars; adjust on READ via the ``ohlcv_adjusted`` view
--     (D2). Adjusted/continuous series are never cached as the source of truth.
--   * Futures ``1d`` close = SETTLEMENT price, never a rollup of intraday (D10).
--   * Multi-timeframe = Option A: ``timeframe`` in the PK ``(symbol, timeframe,
--     ts)``; bars are stored as fetched. Coarser TFs a strategy didn't fetch are
--     derived via continuous aggregates in 11_market_data_caggs.sql.
--   * Every table has a natural-key PK so the engine can ``INSERT … ON CONFLICT
--     … DO UPDATE`` for full idempotency.
--   * Fully idempotent: re-running this script (or container init) is a no-op.
--
-- Rollback (no migration framework — init-scripts only): this schema is
-- self-contained in its own database. To drop it entirely:
--     \c db_market_data
--     DROP SCHEMA IF EXISTS market_data CASCADE;
--   -- then, connected to another DB (e.g. postgres):
--     DROP DATABASE IF EXISTS db_market_data;
-- A fresh container volume re-applies this script from scratch, which is the
-- forward-migration / rollback round-trip exercised by the infra test suite.
-- ============================================================================

\connect db_market_data

-- ``timescaledb`` is enabled for db_market_data by 02_enable_timescaledb.sql;
-- the guard keeps this script self-contained if the ordering ever changes.
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS market_data;

-- ---------------------------------------------------------------------------
-- market_data.ohlcv — raw bars, one row per (symbol, timeframe, bar-open).
-- The canonical store (TimescaleDB hypertable on ``ts``). Equities, futures
-- (continuous ``S501!`` + dated ``S50M2026`` …) and indices all live here,
-- distinguished only by ``symbol``.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_data.ohlcv (
    symbol        TEXT           NOT NULL,
    timeframe     TEXT           NOT NULL CHECK (timeframe IN ('1d', '1h', '5m')),
    ts            TIMESTAMPTZ    NOT NULL,
    open          NUMERIC(18, 6) NOT NULL CHECK (open  > 0),
    high          NUMERIC(18, 6) NOT NULL CHECK (high  > 0),
    low           NUMERIC(18, 6) NOT NULL CHECK (low   > 0),
    close         NUMERIC(18, 6) NOT NULL CHECK (close > 0),
    volume        NUMERIC(20, 4) NOT NULL DEFAULT 0 CHECK (volume >= 0),
    open_interest NUMERIC(20, 4) CHECK (open_interest IS NULL OR open_interest >= 0),
    source        TEXT           NOT NULL DEFAULT 'tvkit',
    ingested_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    CONSTRAINT ck_ohlcv_high_low CHECK (high >= low),
    CONSTRAINT pk_ohlcv PRIMARY KEY (symbol, timeframe, ts)
);

SELECT create_hypertable(
    'market_data.ohlcv',
    'ts',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists       => TRUE
);

-- Read-path index: the canonical query is
--   WHERE symbol = $1 AND timeframe = $2 [AND ts >= $3] ORDER BY ts DESC
CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_tf_ts
    ON market_data.ohlcv (symbol, timeframe, ts DESC);

-- Per-timeframe policy: compress closed chunks after ~7 days. 5m/1h benefit
-- most; 1d is tiny and kept forever (no retention/drop policy — D9/§3).
ALTER TABLE market_data.ohlcv SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, timeframe',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('market_data.ohlcv', INTERVAL '7 days', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- market_data.corporate_actions — splits / dividends (equities) AND futures
-- roll dates (``S501!`` back-adjustment). The ``ratio`` column is the
-- multiplicative price BACK-ADJUSTMENT factor applied to bars dated strictly
-- before ``ex_date`` (the engine computes it in Phase 2: 1/split_factor for a
-- split; (close − dividend)/close for a dividend; the roll-gap multiplier for a
-- roll). ``amount`` records the raw human-readable magnitude (cash dividend,
-- split label, roll price gap) for audit. Adjust-on-read (D2/D10) consumes
-- ``ratio`` via the ohlcv_adjusted view below. Low-cardinality point-lookup
-- table — a plain table, not a hypertable.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_data.corporate_actions (
    symbol      TEXT           NOT NULL,
    ex_date     DATE           NOT NULL,
    action_type TEXT           NOT NULL CHECK (action_type IN ('split', 'dividend', 'roll')),
    ratio       NUMERIC(18, 8) CHECK (ratio IS NULL OR ratio > 0),
    amount      NUMERIC(18, 6),
    note        TEXT,
    ingested_at TIMESTAMPTZ    NOT NULL DEFAULT now(),
    CONSTRAINT pk_corporate_actions PRIMARY KEY (symbol, ex_date, action_type)
);
CREATE INDEX IF NOT EXISTS idx_corporate_actions_symbol_exdate
    ON market_data.corporate_actions (symbol, ex_date DESC);

-- ---------------------------------------------------------------------------
-- market_data.universe_membership — as-of dated, point-in-time index
-- constituents (seeded later from the monthly universe snapshots). Prevents
-- survivorship / look-ahead bias in backtests (Phase 1 ships the schema only).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_data.universe_membership (
    as_of       DATE        NOT NULL,
    symbol      TEXT        NOT NULL,
    index_name  TEXT        NOT NULL DEFAULT 'SET',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_universe_membership PRIMARY KEY (as_of, symbol, index_name)
);
CREATE INDEX IF NOT EXISTS idx_universe_membership_asof
    ON market_data.universe_membership (index_name, as_of DESC);

-- ---------------------------------------------------------------------------
-- market_data.ohlcv_adjusted — adjust-on-read VIEW (D2).
-- A view (NOT a continuous aggregate) so it recomputes on every read and
-- therefore AUTOMATICALLY reflects a newly inserted corporate_actions row —
-- the Phase 1 success criterion. The adjustment factor for each bar is the
-- cumulative product of ``ratio`` over all actions for that symbol whose
-- ``ex_date`` is strictly AFTER the bar's date (back-adjustment). Postgres has
-- no product aggregate, so the standard exp(sum(ln(·))) identity is used
-- (``ratio`` is constrained > 0).
--
-- Phase 1 ships the equity split/dividend path as the proven, testable case
-- (ratio-driven). Futures roll back-adjustment uses the same mechanism via
-- action_type='roll' rows; the EXACT tfex roll parity math is ported in Phase 4
-- (ADR §7) where it is diff-tested before cutover. Volume / open_interest are
-- passed through unadjusted in Phase 1.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW market_data.ohlcv_adjusted AS
SELECT
    o.symbol,
    o.timeframe,
    o.ts,
    (o.open  * f.adjustment_factor)::NUMERIC(18, 6) AS open,
    (o.high  * f.adjustment_factor)::NUMERIC(18, 6) AS high,
    (o.low   * f.adjustment_factor)::NUMERIC(18, 6) AS low,
    (o.close * f.adjustment_factor)::NUMERIC(18, 6) AS close,
    o.volume,
    o.open_interest,
    o.source,
    o.ingested_at,
    f.adjustment_factor
FROM market_data.ohlcv o
CROSS JOIN LATERAL (
    SELECT COALESCE(
        (SELECT exp(sum(ln(ca.ratio)))
         FROM market_data.corporate_actions ca
         WHERE ca.symbol = o.symbol
           AND ca.ratio IS NOT NULL
           AND ca.ex_date > (o.ts AT TIME ZONE 'UTC')::date),
        1.0
    ) AS adjustment_factor
) f;
