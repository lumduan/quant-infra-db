-- ============================================================================
-- 20_schema_crypto.sql
-- ----------------------------------------------------------------------------
-- Durable hot-tier store for the Crypto Capture engine (feature-crypto-engine,
-- Phase 1 — 24/7 digital-asset L2 depth + time & sales from Binance TH + Bitkub,
-- + Binance Global as a fallback for the USDT legs). Lives in its OWN database
-- ``db_crypto`` (created in 01_create_databases.sql), schema ``crypto``, mirroring
-- the db_ticker / db_orderbook precedent so the crypto store is independently owned
-- (ADR CX1/D1 — a pure data plane; the venues are public no-auth WebSockets so the
-- engine holds no broker credential at all).
--
-- The standalone ``quant-crypto-engine`` service (host :9100, market-data plane,
-- sibling to quant-orderbook-engine / quant-ticker-engine) is the sole writer. It
-- captures depth + trades per venue, each banked to its OWN append-only binary raw
-- log (the system of record); THIS hot tier is the regenerable queryable mirror.
-- Consumers READ (Phase 4, gateway-proxied under /api/v2/engines/crypto/*); they
-- never write ``crypto.*``.
--
-- Conventions (mirror 17_schema_ticker.sql + 14_schema_orderbook.sql):
--   * TimescaleDB hypertables for the high-volume streams; 1-day chunks.
--   * Prices/sizes Decimal-on-wire, NEVER float. CRYPTO DEVIATION (ADR CX11):
--     sizes are FRACTIONAL -> NUMERIC(28,10) (NOT the SET/TFEX BIGINT volume);
--     price widened to NUMERIC(20,8) for THB magnitude (BTC/THB ~2.1M) + USDT
--     precision headroom. (Precision provisional — confirm against real ticks.)
--   * PER-VENUE single-source tracks, NEVER cross-venue-unioned (ADR CX2): ``venue``
--     is the exchange (a closed enum); ``source`` is the capture track (= venue for
--     a single node now; venue+node under later CR-style redundancy). Cross-venue
--     reconciliation (e.g. the THB-premium) is a DERIVED layer, never a byte-merge.
--   * DUAL TIMESTAMP (ADR CX3): exchange_ts_ms nullable (Bitkub depth carries no
--     venue clock; Bitkub trades are seconds-granular), local_ts_us always present +
--     authoritative for Bitkub. Capture clocks are bigint nanoseconds.
--   * APPEND-ONLY (the regenerable echo of the binary raw logs): SELECT, INSERT
--     only — NO UPDATE/DELETE (raw is the immutable system of record; ADR CX7/CX10).
-- ============================================================================

\c db_crypto

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE SCHEMA IF NOT EXISTS crypto;

-- ---------------------------------------------------------------------------
-- crypto.raw_events — verbatim queryable echo of the append-only raw log (mirrors
-- orderbook.raw_events). ``stream`` = 'depth'|'trade'|'aggTrade'|'snapshot'|'control'.
-- The one JSON parse happens off the hot path / at compaction (ADR CX7).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crypto.raw_events (
    ts             TIMESTAMPTZ NOT NULL,
    venue          TEXT        NOT NULL
                     CHECK (venue IN ('binance_th', 'binance_global', 'bitkub')),
    source         TEXT        NOT NULL,   -- capture track (= venue now; venue+node later)
    symbol         TEXT,                   -- canonical 'BTC/THB' (NULL for control frames)
    stream         TEXT        NOT NULL,   -- depth | trade | aggTrade | snapshot | control
    seq            BIGINT,                 -- Binance final_update_id / trade_id; NULL Bitkub
    payload        JSONB       NOT NULL,   -- the normalized envelope
    exchange_ts_ms BIGINT,                 -- nullable venue clock (ADR CX3)
    local_ts_us    BIGINT      NOT NULL,   -- receive µs (authoritative for Bitkub)
    t_ingest_ns    BIGINT      NOT NULL,
    t_mono_ns      BIGINT      NOT NULL
);
SELECT create_hypertable('crypto.raw_events', 'ts',
    chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_crypto_raw_venue_sym_ts
    ON crypto.raw_events (venue, symbol, ts DESC);

-- ---------------------------------------------------------------------------
-- crypto.trades — time & sales, one row per print. Binance carries trade_id +
-- is_buyer_maker + a ms clock; Bitkub carries neither + a SECONDS clock (degraded).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crypto.trades (
    ts             TIMESTAMPTZ  NOT NULL,
    venue          TEXT         NOT NULL
                     CHECK (venue IN ('binance_th', 'binance_global', 'bitkub')),
    source         TEXT         NOT NULL,   -- capture track (ADR CX2)
    symbol         TEXT         NOT NULL,   -- canonical 'BTC/THB'
    price          NUMERIC(20, 8)  NOT NULL CHECK (price > 0),
    size           NUMERIC(28, 10) NOT NULL CHECK (size >= 0),  -- FRACTIONAL (ADR CX11) — not bigint
    side           TEXT         CHECK (side IS NULL OR side IN ('buy', 'sell')),  -- aggressor
    trade_id       BIGINT,                  -- Binance; NULL Bitkub
    is_buyer_maker BOOLEAN,                 -- Binance m; NULL Bitkub
    exchange_ts_ms BIGINT,                  -- nullable (Bitkub seconds->ms, degraded)
    local_ts_us    BIGINT       NOT NULL,   -- authoritative for Bitkub (ADR CX3)
    t_ingest_ns    BIGINT       NOT NULL,
    t_mono_ns      BIGINT       NOT NULL
);
SELECT create_hypertable('crypto.trades', 'ts',
    chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_crypto_trades_sym_ts
    ON crypto.trades (symbol, ts DESC);
CREATE INDEX IF NOT EXISTS idx_crypto_trades_venue_sym_ts
    ON crypto.trades (venue, symbol, ts DESC);

-- ---------------------------------------------------------------------------
-- crypto.book_updates — L2 changes. Binance = diff-depth (update_type='diff';
-- first/final_update_id = U/u; prev_update_id = pu, the per-symbol contiguity key,
-- ADR CX4). Bitkub depthchanged = full 'snapshot' (no ids, no venue clock).
-- Levels are [[price, size], ...] as JSONB strings (Decimal-on-wire, ADR CX11).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crypto.book_updates (
    ts              TIMESTAMPTZ NOT NULL,
    venue           TEXT        NOT NULL
                      CHECK (venue IN ('binance_th', 'binance_global', 'bitkub')),
    source          TEXT        NOT NULL,   -- capture track (ADR CX2)
    symbol          TEXT        NOT NULL,
    update_type     TEXT        NOT NULL CHECK (update_type IN ('diff', 'snapshot')),
    first_update_id BIGINT,                 -- Binance U; NULL Bitkub
    final_update_id BIGINT,                 -- Binance u; NULL Bitkub
    prev_update_id  BIGINT,                 -- Binance pu (== prev u per symbol); NULL Bitkub
    bids            JSONB       NOT NULL,
    asks            JSONB       NOT NULL,
    exchange_ts_ms  BIGINT,                 -- nullable (Bitkub depth has NONE, ADR CX3)
    local_ts_us     BIGINT      NOT NULL,
    t_ingest_ns     BIGINT      NOT NULL,
    t_mono_ns       BIGINT      NOT NULL
);
SELECT create_hypertable('crypto.book_updates', 'ts',
    chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_crypto_book_venue_sym_ts
    ON crypto.book_updates (venue, symbol, ts DESC);

-- ---------------------------------------------------------------------------
-- Compression + a PROVISIONAL retention backstop (mirror 17_schema_ticker.sql;
-- Phase-2-calibration-deferred against real 24/7 volume). 30 days >> the hot window;
-- the engine's cold-verified pruning LEADS (ADR CX16 store->prune) — never drop
-- ahead of a verified cold copy; the raw logs are the non-backfillable record.
-- ---------------------------------------------------------------------------
ALTER TABLE crypto.raw_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('crypto.raw_events', INTERVAL '3 days', if_not_exists => TRUE);
SELECT add_retention_policy('crypto.raw_events', INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE crypto.trades SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('crypto.trades', INTERVAL '3 days', if_not_exists => TRUE);
SELECT add_retention_policy('crypto.trades', INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE crypto.book_updates SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('crypto.book_updates', INTERVAL '3 days', if_not_exists => TRUE);
SELECT add_retention_policy('crypto.book_updates', INTERVAL '30 days', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- Service-role grants (least-privilege; mirror 17_schema_ticker.sql:98-106).
-- ``quant`` is the shared service role the engine connects as; created here if
-- absent with the placeholder compose password — operators MUST override per host.
-- Append-only capture: SELECT, INSERT — NO UPDATE/DELETE. (DQ tables + the monitor
-- read-role grant live in 21_crypto_dq.sql, after every crypto table exists.)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'quant') THEN
        CREATE ROLE quant LOGIN PASSWORD 'quant';
    END IF;
END $$;

GRANT USAGE ON SCHEMA crypto TO quant;
GRANT SELECT, INSERT ON crypto.raw_events   TO quant;
GRANT SELECT, INSERT ON crypto.trades       TO quant;
GRANT SELECT, INSERT ON crypto.book_updates TO quant;
