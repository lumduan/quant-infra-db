-- ============================================================================
-- 14_schema_orderbook.sql
-- ----------------------------------------------------------------------------
-- Durable hot-tier store for the Order-Book Capture engine
-- (feature-orderbook-engine, Phase 1). Lives in its OWN database
-- ``db_orderbook`` (created in 01_create_databases.sql), inside an
-- ``orderbook`` schema, mirroring the db_market_data / db_execution precedent
-- so the capture store is independently owned and decoupled from db_gateway /
-- the strategy DBs.
--
-- The standalone ``quant-orderbook-engine`` service (host :8600, market-data
-- plane, sibling to quant-marketdata-engine) is the eventual sole writer.
-- It captures L2 depth + time & sales from the Liberator ws feed; the
-- APPEND-ONLY BINARY RAW LOG on NVMe (OB15) is the true system of record, and
-- the Parquet cold tier is the training tier. THIS hot tier is the queryable
-- mirror — everything here is regenerable from the immutable raw log.
-- Strategies, OpenBB and the gateway READ (Phase 4, gateway-proxied under
-- /api/v2/engines/orderbook/*); they never write ``orderbook.*``. (D1
-- two-planes boundary: this is a pure data plane — it never touches the
-- order-routing path.)
--
-- Conventions:
--   * TimescaleDB hypertables for the high-volume event streams
--     (``raw_events``, ``trades``, ``book_snapshots``) — the OPPOSITE profile
--     from db_execution's plain-table command plane: always-on streaming,
--     thousands of events/sec near the close, ~1M events/day (Phase 1 TFEX).
--     Chunking + compression are exactly what this data wants. The reference
--     point-lookup tables (``settlements``, ``gap_windows``, ``dq_manifests``)
--     are PLAIN tables — low cardinality, no time-series scan profile.
--   * ``raw_events`` is APPEND-ONLY and immutable (OB3) — the queryable echo of
--     the binary raw log; no natural-key PK / ON CONFLICT (raw is never
--     revised; a duplicate would be a capture bug to surface, not silently
--     swallow). ``book_snapshots`` is DERIVED + regenerable (rebuilt from raw),
--     NOT raw — kept physically separate per OB3.
--   * Prices NUMERIC(18, 6) — matches the db_market_data shared-store contract
--     (6-dp on the wire; money is Decimal-on-wire, never float). Volume BIGINT
--     (SET shares / TFEX contracts are integral). Settlement price is the
--     overnight mean-reversion anchor for downstream IV/greeks (a derived
--     layer, kept out of this hot tier).
--   * Capture timestamps are stored as BIGINT nanoseconds (chrony-synced wall
--     ``t_ingest_ns`` + jitter-free monotonic ``t_mono_ns`` + venue
--     ``t_event_ns``, nullable) exactly as the binary-log spec (OB15) carries
--     them — full ns resolution, no lossy TIMESTAMPTZ round-trip. ``ts`` is the
--     derived TIMESTAMPTZ partition/order column (the wall clock, UTC; display
--     Asia/Bangkok at the edge), so the hot tier stays time-queryable.
--   * ``vs_seq`` is Liberator's per-push sequence (BIGINT, nullable — not every
--     namespace carries one). Phase-0.5 finding: ``vs`` is a large global,
--     time-derived monotonic value SHARED across rooms (not strictly +1 per
--     room), so gap detection must not key off per-room ``vs`` skips. Stored
--     verbatim; gap windows are computed by the evening compaction (OB17), not
--     enforced here.
--   * Enums (``market``, ``aggressor_side``, ``quality_grade``) are TEXT +
--     CHECK constraints (the 10/12 precedent), not Postgres ENUM types —
--     idempotent under re-run, evolvable via DROP/ADD CONSTRAINT.
--   * Fully idempotent: re-running this script (or container init) is a no-op
--     (IF NOT EXISTS everywhere; create_hypertable / add_*_policy take
--     ``if_not_exists => TRUE``).
--
-- Retention: PROVISIONAL. The hot tier is pruned after the cold Parquet is
-- SHA-256-verified (engine config ``HOT_RETENTION_DAYS``, default ~7 days). The
-- DB-side retention policies below are a conservative backstop; the FINAL
-- retention/compression cadence is CALIBRATION-DEFERRED to Stage B against real
-- captured volume + the cold-offload SLA (per the engine ROADMAP §1.6 "tuned
-- for Phase-1 volume" + §1.7 hot-tier pruning). Never drop ``raw_events`` ahead
-- of a verified cold copy.
--
-- Rollback (no migration framework — init-scripts only): this schema is
-- self-contained in its own database. To drop it entirely:
--     \c db_orderbook
--     DROP SCHEMA IF EXISTS orderbook CASCADE;
--   -- then, connected to another DB (e.g. postgres):
--     DROP DATABASE IF EXISTS db_orderbook;
-- A fresh container volume re-applies this script from scratch.
-- ============================================================================

\connect db_orderbook

-- ``timescaledb`` is enabled for db_orderbook by 02_enable_timescaledb.sql;
-- the guard keeps this script self-contained if the ordering ever changes.
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS orderbook;

-- ---------------------------------------------------------------------------
-- orderbook.raw_events — the queryable echo of the append-only binary raw log
-- (OB3/OB15). One typed row per captured Liberator frame, ALL namespaces
-- interleaved (BidOfferV2 book, TickerV2 T&S, MarketIndexV2, MarketStatusV2,
-- TFEXDashboardV2, StockV2). Append-only + immutable: the binary log is the
-- true system of record and this is regenerable from it, so there is NO
-- natural-key PK and NO ON CONFLICT — a duplicate is a capture bug to surface.
-- ``payload`` is the raw Socket.IO frame body as JSONB (the single parse off
-- the hot path happens in the evening compaction; this hot-tier write is the
-- queryability convenience, OB7). Hypertable on ``ts`` (wall-clock UTC).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orderbook.raw_events (
    ts          TIMESTAMPTZ NOT NULL,
    source      TEXT        NOT NULL DEFAULT 'liberator',
    market      TEXT        CHECK (market IS NULL OR market IN ('SET', 'TFEX')),
    symbol      TEXT,
    ns          TEXT        NOT NULL,
    vs_seq      BIGINT,
    payload     JSONB       NOT NULL,
    t_ingest_ns BIGINT      NOT NULL,
    t_mono_ns   BIGINT      NOT NULL,
    t_event_ns  BIGINT
);

SELECT create_hypertable(
    'orderbook.raw_events',
    'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

-- Read path: "all events for one symbol, newest first" + namespace filtering.
CREATE INDEX IF NOT EXISTS idx_raw_events_symbol_ts
    ON orderbook.raw_events (symbol, ts DESC);
CREATE INDEX IF NOT EXISTS idx_raw_events_ns_ts
    ON orderbook.raw_events (ns, ts DESC);

-- ---------------------------------------------------------------------------
-- orderbook.trades — time & sales (trade prints) demuxed from TickerV2 (OB11 —
-- mandatory; the execution engine discards these today). One row per print.
-- Hypertable on ``ts``. ``aggressor_side`` is the trade-initiator side when the
-- feed exposes it (nullable — not always present).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orderbook.trades (
    ts             TIMESTAMPTZ    NOT NULL,
    symbol         TEXT           NOT NULL,
    market         TEXT           NOT NULL CHECK (market IN ('SET', 'TFEX')),
    price          NUMERIC(18, 6) NOT NULL CHECK (price > 0),
    volume         BIGINT         NOT NULL CHECK (volume >= 0),
    aggressor_side TEXT           CHECK (aggressor_side IS NULL
                                         OR aggressor_side IN ('BUY', 'SELL'))
);

SELECT create_hypertable(
    'orderbook.trades',
    'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts
    ON orderbook.trades (symbol, ts DESC);

-- ---------------------------------------------------------------------------
-- orderbook.book_snapshots — DERIVED L2 snapshots (OB3: regenerable, NOT raw),
-- reconstructed from raw_events by the derived layer (Phase 3). ``bid_levels``
-- / ``ask_levels`` are JSONB arrays of {price, volume} levels (full depth the
-- feed pushed — L5–L10, never truncated to L1, OB11). ``vs_seq`` carries the
-- source push sequence. Hypertable on ``ts``; freely rebuildable from raw, so
-- no natural-key PK.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orderbook.book_snapshots (
    ts         TIMESTAMPTZ NOT NULL,
    symbol     TEXT        NOT NULL,
    market     TEXT        NOT NULL CHECK (market IN ('SET', 'TFEX')),
    bid_levels JSONB       NOT NULL,
    ask_levels JSONB       NOT NULL,
    vs_seq     BIGINT
);

SELECT create_hypertable(
    'orderbook.book_snapshots',
    'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_book_snapshots_symbol_ts
    ON orderbook.book_snapshots (symbol, ts DESC);

-- ---------------------------------------------------------------------------
-- orderbook.settlements — TFEX daily settlement prices (the overnight
-- mean-reversion anchor / "true price" for downstream IV/greeks). Low
-- cardinality, point-lookup by (date, symbol) — a PLAIN table, not a
-- hypertable. PK = (date, symbol) gives idempotent ON CONFLICT upsert.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orderbook.settlements (
    date             DATE           NOT NULL,
    symbol           TEXT           NOT NULL,
    settlement_price NUMERIC(18, 6) NOT NULL CHECK (settlement_price > 0),
    source           TEXT           NOT NULL DEFAULT 'liberator',
    CONSTRAINT pk_settlements PRIMARY KEY (date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_settlements_symbol_date
    ON orderbook.settlements (symbol, date DESC);

-- ---------------------------------------------------------------------------
-- orderbook.gap_windows — explicit unknown-state intervals (OB6). On reconnect
-- ⇒ re-snapshot ⇒ a gap is MARKED here; downstream consumers must EXCLUDE these
-- windows (never silently interpolate across them). Identity PK (append-only,
-- insertion-ordered). Low cardinality — a PLAIN table. ``from_vs`` / ``to_vs``
-- bound the missing sequence span; ``wall_start`` / ``wall_end`` give the
-- wall-clock window for time-range exclusion.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orderbook.gap_windows (
    gap_id        BIGINT      GENERATED ALWAYS AS IDENTITY,
    symbol        TEXT        NOT NULL,
    market        TEXT        NOT NULL CHECK (market IN ('SET', 'TFEX')),
    from_vs       BIGINT,
    to_vs         BIGINT,
    missing_count INT         CHECK (missing_count IS NULL OR missing_count >= 0),
    wall_start    TIMESTAMPTZ NOT NULL,
    wall_end      TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_gap_windows PRIMARY KEY (gap_id)
);
-- Exclusion lookup: "gap windows for one symbol overlapping a time range".
CREATE INDEX IF NOT EXISTS idx_gap_windows_symbol_wall
    ON orderbook.gap_windows (symbol, wall_start, wall_end);

-- ---------------------------------------------------------------------------
-- orderbook.dq_manifests — per-day data-quality manifest (OB17), the training
-- gate. ``quality_grade`` is GREEN (training-safe) / AMBER (usable with
-- gap-windows excluded) / RED (auto-quarantined). ``manifest_json`` holds the
-- full per-room / disconnect / integrity / settlement breakdown. Indexed beside
-- the Parquet on the NAS. Low cardinality (one row per source per day) — a
-- PLAIN table; PK = (date, source) for idempotent re-emit.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orderbook.dq_manifests (
    date          DATE  NOT NULL,
    source        TEXT  NOT NULL DEFAULT 'liberator',
    quality_grade TEXT  NOT NULL CHECK (quality_grade IN ('GREEN', 'AMBER', 'RED')),
    manifest_json JSONB NOT NULL,
    CONSTRAINT pk_dq_manifests PRIMARY KEY (date, source)
);
CREATE INDEX IF NOT EXISTS idx_dq_manifests_grade_date
    ON orderbook.dq_manifests (quality_grade, date DESC);

-- ---------------------------------------------------------------------------
-- Compression + PROVISIONAL retention on the three hypertables. Compress
-- closed chunks after ~3 days (event streams are write-once, read-mostly-recent
-- — older chunks compress well, segmented by symbol). Retention is a
-- conservative backstop only: data is pruned from the hot tier once the cold
-- Parquet is SHA-256-verified (engine ``HOT_RETENTION_DAYS``); these DB
-- policies are CALIBRATION-DEFERRED to Stage B against real volume + the
-- cold-offload SLA. Never drop ``raw_events`` ahead of a verified cold copy.
-- ---------------------------------------------------------------------------
ALTER TABLE orderbook.raw_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, ns',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('orderbook.raw_events', INTERVAL '3 days', if_not_exists => TRUE);
-- PROVISIONAL — Stage-B-calibrated. 30 days >> the ~7-day hot window so the
-- engine's cold-verified pruning leads; this is a safety backstop, not the SLA.
SELECT add_retention_policy('orderbook.raw_events', INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE orderbook.trades SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('orderbook.trades', INTERVAL '3 days', if_not_exists => TRUE);
SELECT add_retention_policy('orderbook.trades', INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE orderbook.book_snapshots SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('orderbook.book_snapshots', INTERVAL '3 days', if_not_exists => TRUE);
SELECT add_retention_policy('orderbook.book_snapshots', INTERVAL '30 days', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- Service-role grants (least-privilege; mirrors the 12_schema_execution.sql
-- block). ``quant`` is the shared service role this stack's engines connect as;
-- created here if absent with the same placeholder password the compose files
-- ship — operators MUST override it per machine (ALTER ROLE quant PASSWORD ...)
-- outside the repo.
--
--   * raw_events / trades / book_snapshots: SELECT, INSERT — the capture +
--     derived writers append; NO UPDATE/DELETE (raw is immutable; derived is
--     rebuilt by truncate-free regeneration, not in-place mutation).
--   * settlements / dq_manifests: SELECT, INSERT, UPDATE — these are
--     idempotent upserts keyed by (date, symbol) / (date, source); a re-emit
--     ON CONFLICT DO UPDATE needs UPDATE.
--   * gap_windows: SELECT, INSERT — append-only audit of unknown-state windows.
--   * sequences: USAGE for the gap_windows identity column.
--   * No DELETE anywhere; strategies, OpenBB and the gateway READ via the
--     gateway proxy (Phase 4) and get no write grant on ``orderbook.*``.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'quant') THEN
        CREATE ROLE quant LOGIN PASSWORD 'quant';
    END IF;
END $$;

GRANT USAGE ON SCHEMA orderbook TO quant;
GRANT SELECT, INSERT ON orderbook.raw_events TO quant;
GRANT SELECT, INSERT ON orderbook.trades TO quant;
GRANT SELECT, INSERT ON orderbook.book_snapshots TO quant;
GRANT SELECT, INSERT, UPDATE ON orderbook.settlements TO quant;
GRANT SELECT, INSERT ON orderbook.gap_windows TO quant;
GRANT SELECT, INSERT, UPDATE ON orderbook.dq_manifests TO quant;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA orderbook TO quant;
