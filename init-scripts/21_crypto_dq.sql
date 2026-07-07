-- ============================================================================
-- 21_crypto_dq.sql
-- ----------------------------------------------------------------------------
-- Per-(date, source) data-quality manifests + gap windows for the Crypto engine
-- (feature-crypto-engine, Phase 2). Mirrors 18_ticker_dq.sql. ``source`` is the
-- per-venue capture track (ADR CX2) — each track graded INDEPENDENTLY, NEVER
-- cross-venue-unioned. ``date`` is the UTC LOGICAL DAY (ADR CX5 — crypto never
-- closes; the "close" is UTC-midnight).
--   * dq_manifests: idempotent upsert keyed (date, source) -> SELECT, INSERT, UPDATE.
--   * gap_windows: append-only -> SELECT, INSERT. Binance carries EXACT sequence
--     gaps (from_seq/to_seq off the U/u/pu chain, ADR CX4); Bitkub is DEGRADED (no
--     venue sequence) -> NULL seq + a conservative local-silence / per-reconnect gap.
--
-- Also grants the read-only ``monitor`` role SELECT on the whole ``crypto`` schema.
-- This lives HERE (not in 19_monitor_role.sql) because 19_ runs BEFORE db_crypto
-- exists; by this point 20_ + 21_ have created every crypto table, so
-- ``GRANT SELECT ON ALL TABLES`` covers them all.
--
-- NOTE: init-scripts auto-run only on a FRESH postgres volume. On an already-
-- initialised cluster, apply 01/20/21 once manually + idempotently, e.g.:
--   docker exec -i quant-postgres psql -U postgres -f - < 20_schema_crypto.sql
-- ============================================================================

\c db_crypto

CREATE TABLE IF NOT EXISTS crypto.dq_manifests (
    date          DATE NOT NULL,                 -- UTC logical day (ADR CX5)
    source        TEXT NOT NULL,                 -- per-venue capture track (ADR CX2)
    quality_grade TEXT NOT NULL CHECK (quality_grade IN ('GREEN', 'AMBER', 'RED')),
    manifest_json JSONB NOT NULL,
    CONSTRAINT pk_crypto_dq_manifests PRIMARY KEY (date, source)
);

CREATE TABLE IF NOT EXISTS crypto.gap_windows (
    gap_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date          DATE NOT NULL,
    source        TEXT NOT NULL,                 -- per-venue capture track
    symbol        TEXT NOT NULL,
    stream        TEXT NOT NULL,                 -- depth | trade
    from_seq      BIGINT,                        -- Binance-exact; NULL Bitkub (degraded, ADR CX4)
    to_seq        BIGINT,
    missing_count INT,
    wall_start    TIMESTAMPTZ NOT NULL,
    wall_end      TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crypto_gap_date_source
    ON crypto.gap_windows (date, source);

-- ---------------------------------------------------------------------------
-- Service-role grants (``quant`` created in 20_schema_crypto.sql).
--   * dq_manifests: SELECT, INSERT, UPDATE — idempotent per-(date, source) upsert.
--   * gap_windows: SELECT, INSERT — append-only. NO DELETE anywhere (ADR CX10).
-- ---------------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE ON crypto.dq_manifests TO quant;
GRANT SELECT, INSERT         ON crypto.gap_windows  TO quant;

-- ---------------------------------------------------------------------------
-- Read-only ``monitor`` role for the quant-monitor dashboard (host :8900). The
-- role is created cluster-global in 19_monitor_role.sql; guard for a crypto-only
-- manual apply. SELECT-only on the whole crypto schema — no write/DDL.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'monitor') THEN
        CREATE ROLE monitor LOGIN PASSWORD 'monitor';  -- placeholder; ALTER per host
    END IF;
END $$;

GRANT CONNECT ON DATABASE db_crypto TO monitor;
GRANT USAGE ON SCHEMA crypto TO monitor;
GRANT SELECT ON ALL TABLES IN SCHEMA crypto TO monitor;
ALTER DEFAULT PRIVILEGES IN SCHEMA crypto GRANT SELECT ON TABLES TO monitor;
