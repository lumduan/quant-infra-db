-- ============================================================================
-- 19_monitor_role.sql
-- ----------------------------------------------------------------------------
-- Read-only `monitor` role for the quant-monitor system dashboard (host :8900).
-- SELECT-only on the order-book + ticker capture stores so the monitor can read
-- "rows captured today" + the latest DQ grade WITHOUT any write/DDL capability.
-- Mirrors the role-create idiom in 14_schema_orderbook.sql / 17_schema_ticker.sql.
--
-- The role is cluster-global (created once); the GRANTs are per-database, so this
-- file switches databases with \c (works via `psql -f`). A role defaults to NO
-- privileges on a database, so `monitor` can ONLY read what is granted below.
--
-- NOTE: init-scripts auto-run only on a FRESH postgres data volume. On an
-- already-initialised cluster, apply once manually (idempotent):
--     docker exec -i quant-postgres psql -U postgres -f - < 19_monitor_role.sql
-- The placeholder password MUST be overridden per host (never commit the real one):
--     ALTER ROLE monitor PASSWORD '<strong-secret>';
-- and supplied to the service via QUANT_MONITOR_PG_*_DSN (gitignored .env).
-- ============================================================================

\c db_orderbook

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'monitor') THEN
        CREATE ROLE monitor LOGIN PASSWORD 'monitor';  -- placeholder; ALTER per host
    END IF;
END $$;

GRANT CONNECT ON DATABASE db_orderbook TO monitor;
GRANT USAGE ON SCHEMA orderbook TO monitor;
GRANT SELECT ON ALL TABLES IN SCHEMA orderbook TO monitor;
ALTER DEFAULT PRIVILEGES IN SCHEMA orderbook GRANT SELECT ON TABLES TO monitor;

\c db_ticker

GRANT CONNECT ON DATABASE db_ticker TO monitor;
GRANT USAGE ON SCHEMA ticker TO monitor;
GRANT SELECT ON ALL TABLES IN SCHEMA ticker TO monitor;
ALTER DEFAULT PRIVILEGES IN SCHEMA ticker GRANT SELECT ON TABLES TO monitor;
