-- ============================================================================
-- 18_ticker_dq.sql
-- ----------------------------------------------------------------------------
-- Phase-2 data-quality tables for the Ticker engine (feature-ticker-engine
-- Phase 2 — compaction + per-source DQ). Lives in db_ticker, inside the existing
-- `ticker` schema (created in 17_schema_ticker.sql). Mirrors the orderbook DQ
-- tables (14_schema_orderbook.sql) but for the ticker's TWO INDEPENDENT source
-- tracks (TK2): a `source` column distinguishes `liberator` (carries venue `vs`)
-- from `streaming_pro` (carries per-print `seq`, no `vs` — SPC-Gate-2). The two
-- tracks are NEVER union-day'd. The append-only binary raw logs remain the system
-- of record; these tables are the regenerable per-source DQ ledger written by the
-- evening `compact-day --source {liberator,streaming_pro}` CLI.
-- ============================================================================

\connect db_ticker

CREATE SCHEMA IF NOT EXISTS ticker;

-- ---------------------------------------------------------------------------
-- ticker.dq_manifests — one DQ manifest per (date, source) (GREEN/AMBER/RED +
-- the full manifest JSON). PK (date, source) ⇒ idempotent upsert: re-running
-- compact-day for a day overwrites in place (never a duplicate row).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ticker.dq_manifests (
    date          DATE  NOT NULL,
    source        TEXT  NOT NULL CHECK (source IN ('liberator', 'streaming_pro')),
    quality_grade TEXT  NOT NULL CHECK (quality_grade IN ('GREEN', 'AMBER', 'RED')),
    manifest_json JSONB NOT NULL,
    CONSTRAINT pk_ticker_dq_manifests PRIMARY KEY (date, source)
);
CREATE INDEX IF NOT EXISTS idx_ticker_dq_grade_date
    ON ticker.dq_manifests (quality_grade, date DESC);

-- ---------------------------------------------------------------------------
-- ticker.gap_windows — append-only audit of capture gaps (one row per symbol
-- per gap). Carries a `source` column (the two tracks, TK2). `from_vs`/`to_vs`/
-- `missing_count` are Liberator-only (NULL for source=3 streaming_pro, which has
-- no venue sequence). Gaps come from control records + all-namespace silence,
-- NEVER from per-`vs` skips.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ticker.gap_windows (
    gap_id        BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source        TEXT        NOT NULL CHECK (source IN ('liberator', 'streaming_pro')),
    symbol        TEXT        NOT NULL,
    market        TEXT        NOT NULL CHECK (market IN ('SET', 'TFEX')),
    from_vs       BIGINT,
    to_vs         BIGINT,
    missing_count INT         CHECK (missing_count IS NULL OR missing_count >= 0),
    wall_start    TIMESTAMPTZ NOT NULL,
    wall_end      TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ticker_gap_symbol_wall
    ON ticker.gap_windows (symbol, wall_start, wall_end);

-- ---------------------------------------------------------------------------
-- Service-role grants (mirror 14_schema_orderbook.sql; `quant` created in 17_*).
--   * dq_manifests: SELECT, INSERT, UPDATE — the idempotent (date, source) upsert.
--   * gap_windows: SELECT, INSERT — append-only audit (no UPDATE/DELETE).
--   * sequences: USAGE, SELECT for the gap_windows identity column.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'quant') THEN
        CREATE ROLE quant LOGIN PASSWORD 'quant';
    END IF;
END $$;

GRANT USAGE ON SCHEMA ticker TO quant;
GRANT SELECT, INSERT, UPDATE ON ticker.dq_manifests TO quant;
GRANT SELECT, INSERT ON ticker.gap_windows TO quant;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ticker TO quant;
