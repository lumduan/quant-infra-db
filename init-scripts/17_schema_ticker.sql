-- ============================================================================
-- 17_schema_ticker.sql
-- ----------------------------------------------------------------------------
-- Durable hot-tier time & sales (T&S) store for the Ticker engine
-- (feature-ticker-engine, Phase 1 — "the tick plane"). Lives in its OWN database
-- ``db_ticker`` (created in 01_create_databases.sql), inside a ``ticker`` schema,
-- mirroring the db_orderbook / db_market_data precedent so the tick store is
-- independently owned (ADR TK10).
--
-- The standalone ``quant-ticker-engine`` service (host :8800, market-data plane,
-- sibling to quant-orderbook-engine) is the sole writer. It captures trade prints
-- from TWO INDEPENDENT upstreams (ADR TK2) — the Liberator ``TickerV2`` feed and
-- the Streaming Pro bridge (svc-3) — each banked to its OWN append-only binary raw
-- log (the true system of record). THIS hot tier is the regenerable queryable
-- mirror. Strategies / OpenBB / the gateway READ (Phase 4, gateway-proxied under
-- /api/v2/engines/ticker/*); they never write ``ticker.*``. (D1 two-planes
-- boundary: a pure data plane — it never touches the order-routing path.)
--
-- Conventions (mirror 14_schema_orderbook.sql):
--   * A TimescaleDB hypertable for the high-volume trade stream (always-on,
--     thousands of prints/sec near the close). Chunking + compression are exactly
--     what this data wants.
--   * Prices NUMERIC(18, 6) (Decimal-on-wire, never float); volume BIGINT.
--   * TWO INDEPENDENT SOURCE TRACKS, never ``vs``-unioned (TK2): the ``source``
--     column tags each row; ``vs`` (venue sequence) is Liberator-only, ``seq``
--     (per-frame print sequence) is Streaming-Pro-only (SPC-Gate-2 — SP carries no
--     venue sequence). Both are nullable. Reconciliation across sources, if ever,
--     is symbol + wall-clock only — never a byte-merge.
--   * ``trades`` is APPEND-ONLY (the regenerable echo of the binary raw logs); no
--     natural-key PK / ON CONFLICT (raw is never revised; a duplicate is a capture
--     bug to surface, not silently swallow). SELECT, INSERT grants only — NO
--     UPDATE/DELETE.
-- ============================================================================

\c db_ticker

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE SCHEMA IF NOT EXISTS ticker;

-- ---------------------------------------------------------------------------
-- ticker.trades — time & sales (trade prints) from two independent upstreams
-- (TK2). One row per print. Hypertable on ``ts``. ``aggressor_side`` is the
-- trade-initiator side when the feed exposes it (nullable). ``source`` tags the
-- upstream track; ``vs`` is the Liberator venue sequence (NULL for SP); ``seq`` is
-- the Streaming-Pro per-frame print sequence (NULL for Liberator).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ticker.trades (
    ts             TIMESTAMPTZ    NOT NULL,
    symbol         TEXT           NOT NULL,
    market         TEXT           NOT NULL CHECK (market IN ('SET', 'TFEX')),
    price          NUMERIC(18, 6) NOT NULL CHECK (price > 0),
    volume         BIGINT         NOT NULL CHECK (volume >= 0),
    aggressor_side TEXT           CHECK (aggressor_side IS NULL
                                         OR aggressor_side IN ('BUY', 'SELL')),
    source         TEXT           NOT NULL CHECK (source IN ('liberator', 'streaming_pro')),
    vs             BIGINT,  -- Liberator venue sequence (NULL for streaming_pro)
    seq            BIGINT   -- Streaming-Pro per-frame print sequence (NULL for liberator)
);

SELECT create_hypertable(
    'ticker.trades',
    'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

-- Read path: "recent trades for one symbol, newest first" + per-source filtering.
CREATE INDEX IF NOT EXISTS idx_ticker_trades_symbol_ts
    ON ticker.trades (symbol, ts DESC);
CREATE INDEX IF NOT EXISTS idx_ticker_trades_source_symbol_ts
    ON ticker.trades (source, symbol, ts DESC);

-- ---------------------------------------------------------------------------
-- Compression + a PROVISIONAL retention policy (mirrors 14_schema_orderbook.sql;
-- Phase-2-calibration-deferred against real volume). 30 days >> the hot window so
-- the engine's cold-verified pruning leads — a safety backstop, not the SLA. The
-- append-only binary raw logs are the non-backfillable system of record; never
-- drop ahead of a verified cold copy.
-- ---------------------------------------------------------------------------
ALTER TABLE ticker.trades SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('ticker.trades', INTERVAL '3 days', if_not_exists => TRUE);
SELECT add_retention_policy('ticker.trades', INTERVAL '30 days', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- Service-role grants (least-privilege; mirrors 14_schema_orderbook.sql).
-- ``quant`` is the shared service role this stack's engines connect as; created
-- here if absent with the placeholder password the compose files ship — operators
-- MUST override it per machine (ALTER ROLE quant PASSWORD ...) outside the repo.
--   * trades: SELECT, INSERT — the capture writer appends; NO UPDATE/DELETE (raw
--     is immutable; the hot tier is rebuilt by regeneration, not in-place mutation).
--   * Strategies / OpenBB / the gateway READ via the gateway proxy (Phase 4) and
--     get no write grant on ``ticker.*``.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'quant') THEN
        CREATE ROLE quant LOGIN PASSWORD 'quant';
    END IF;
END $$;

GRANT USAGE ON SCHEMA ticker TO quant;
GRANT SELECT, INSERT ON ticker.trades TO quant;
