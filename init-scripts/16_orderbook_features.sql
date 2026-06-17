-- ============================================================================
-- 16_orderbook_features.sql
-- ----------------------------------------------------------------------------
-- Derived microstructure features for the Order-Book Capture engine
-- (feature-orderbook-engine, Phase 3.3). One row per source ``book_snapshot``:
-- mid / bid-ask spread / depth (volume) imbalance / Order-Flow Imbalance (OFI),
-- computed offline by the ``compute-features`` CLI from the regenerable
-- ``orderbook.book_snapshots`` (which is itself reconstructed from the immutable
-- raw log — lineage ``raw -> book_snapshots -> microstructure_features``).
--
-- Design (mirrors ``orderbook.book_snapshots`` in 14_schema_orderbook.sql):
--   * DERIVED + freely REGENERABLE (rebuilt from book_snapshots, OB3) — NOT raw.
--     A TimescaleDB HYPERTABLE on ``ts`` (1-day chunks), like book_snapshots:
--     it has the same high-cardinality time-series profile (one row per push,
--     ~200k+ rows/day Phase-1 TFEX). No natural-key PK — the table is rebuilt by
--     truncate-free regeneration, guarded write-once-per-day at the app layer.
--   * Prices are NUMERIC(18,6) — money is Decimal-on-wire, never float, matching
--     the db_market_data / book_snapshots contract (``mid_price``,
--     ``spread_abs``). Statistics internal to the derived layer are DOUBLE
--     PRECISION floats (``spread_rel``, ``imbalance_l1``, ``imbalance_l5``,
--     ``ofi_l1``) per the engine hard rule "features and statistics internal to
--     the derived layer may use float".
--   * Every feature column is NULLABLE: a one-sided / empty book yields NULL
--     mid/spread/imbalance (NULL, never 0 — 0 is a real value); ``ofi_l1`` is
--     NULL for a symbol's first snapshot of the day and for the first snapshot
--     after a gap window (no valid n-1). ``spread_abs`` MAY be <= 0 (an auction
--     crossed/locked book is recorded faithfully, not nulled — phase-gating is a
--     downstream DQ concern).
--   * ``market`` is TEXT + CHECK (the 10/12/14 precedent), not a Postgres ENUM.
--   * ``vs_seq`` is Liberator's per-push sequence carried verbatim from the
--     source ``book_snapshots`` row — lineage back to the L2 push.
--   * Fully idempotent re-apply (IF NOT EXISTS; create_hypertable
--     ``if_not_exists => TRUE``).
--
-- Rollback: ``DROP TABLE IF EXISTS orderbook.microstructure_features;``
-- ============================================================================

\connect db_orderbook

-- ---------------------------------------------------------------------------
-- orderbook.microstructure_features — DERIVED per-snapshot microstructure
-- features (OB3: regenerable, NOT raw), one row per source book_snapshots push.
-- Hypertable on ``ts``; freely rebuildable from book_snapshots, so no
-- natural-key PK (write-once-per-day guard at the app layer, same as
-- book_snapshots / greeks).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orderbook.microstructure_features (
    ts           TIMESTAMPTZ      NOT NULL,
    symbol       TEXT             NOT NULL,
    market       TEXT             NOT NULL CHECK (market IN ('SET', 'TFEX')),
    mid_price    NUMERIC(18, 6),                 -- price -> Decimal; NULL if one-sided
    spread_abs   NUMERIC(18, 6),                 -- price -> Decimal; NULL if one-sided; may be <= 0 (auction)
    spread_rel   DOUBLE PRECISION,               -- ratio statistic -> float; NULL if mid 0/NULL
    imbalance_l1 DOUBLE PRECISION,               -- in [-1, 1]; NULL if both L1 sizes 0
    imbalance_l5 DOUBLE PRECISION,               -- in [-1, 1]; NULL if both L5 sums 0
    ofi_l1       DOUBLE PRECISION,               -- signed volume; NULL on first / post-gap
    vs_seq       BIGINT                          -- lineage back to the source book_snapshots push
);

SELECT create_hypertable(
    'orderbook.microstructure_features',
    'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

-- Read path: "all features for one symbol, newest first".
CREATE INDEX IF NOT EXISTS idx_microstructure_features_symbol_ts
    ON orderbook.microstructure_features (symbol, ts DESC);

-- ---------------------------------------------------------------------------
-- Grants — mirror ``orderbook.book_snapshots``: the derived writer appends;
-- SELECT, INSERT only (NO UPDATE/DELETE — derived is rebuilt by truncate-free
-- regeneration, not in-place mutation; a forced rebuild is an owner
-- ``drop_chunks`` then re-run). This grant lives here (not in
-- 14_schema_orderbook.sql) because the table did not exist when 14's grant
-- block ran.
-- ---------------------------------------------------------------------------
GRANT SELECT, INSERT ON orderbook.microstructure_features TO quant;
