-- ============================================================================
-- 11_market_data_caggs.sql
-- ----------------------------------------------------------------------------
-- Derived-timeframe continuous aggregates for the shared market_data store
-- (feature-market-data-engine, Phase 1). Coarser timeframes a strategy did NOT
-- fetch are DERIVED from the 5m base grain (D10) — a new strategy wanting a new
-- TF costs one CAGG, zero re-fetch. Because every derived TF rolls up the same
-- 5m base, all readers see identical bar boundaries and cannot disagree.
--
-- NOT covered here (by design):
--   * Fetched ``1d`` bars stay AUTHORITATIVE in market_data.ohlcv and are NEVER
--     rolled up from intraday — for futures the daily close is the SETTLEMENT
--     price, not a 5m rollup (D10). So there is no 1d CAGG.
--   * Split/dividend/roll adjustment is the ohlcv_adjusted VIEW in 10_*, not a
--     CAGG (adjusted series change retroactively; never materialise them).
--
-- Order dependency: runs after 10_schema_market_data.sql (needs market_data.ohlcv).
-- Idempotency follows 06_continuous_aggregates.sql exactly:
--   * CREATE MATERIALIZED VIEW IF NOT EXISTS guards the views.
--   * WITH NO DATA defers materialisation to the first scheduled refresh —
--     required because market_data.ohlcv is empty on a fresh container boot.
--   * add_continuous_aggregate_policy(..., if_not_exists => TRUE) guards jobs.
-- ============================================================================

\c db_market_data

-- ---------------------------------------------------------------------------
-- cagg_ohlcv_1h — 1-hour bars derived from the 5m base.
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS market_data.cagg_ohlcv_1h
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket(INTERVAL '1 hour', ts) AS bucket,
    first(open, ts) AS open,
    max(high)       AS high,
    min(low)        AS low,
    last(close, ts) AS close,
    sum(volume)     AS volume
FROM market_data.ohlcv
WHERE timeframe = '5m'
GROUP BY symbol, bucket
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'market_data.cagg_ohlcv_1h',
    start_offset      => INTERVAL '30 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE
);

-- ---------------------------------------------------------------------------
-- cagg_ohlcv_4h — 4-hour bars derived from the 5m base.
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS market_data.cagg_ohlcv_4h
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket(INTERVAL '4 hours', ts) AS bucket,
    first(open, ts) AS open,
    max(high)       AS high,
    min(low)        AS low,
    last(close, ts) AS close,
    sum(volume)     AS volume
FROM market_data.ohlcv
WHERE timeframe = '5m'
GROUP BY symbol, bucket
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'market_data.cagg_ohlcv_4h',
    start_offset      => INTERVAL '30 days',
    end_offset        => INTERVAL '4 hours',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE
);
