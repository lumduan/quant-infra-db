-- Idempotent database creation. PostgreSQL does not support
-- CREATE DATABASE IF NOT EXISTS, so we use psql's \gexec to
-- conditionally execute CREATE only when the database is absent.
SELECT 'CREATE DATABASE db_csm_set'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'db_csm_set')\gexec
SELECT 'CREATE DATABASE db_gateway'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'db_gateway')\gexec
-- db_market_data: shared canonical OHLCV store for the Market Data engine
-- (feature-market-data-engine Phase 1). A dedicated database (not a schema in
-- db_gateway) keeps the canonical store independently owned per ADR D4/D7.
SELECT 'CREATE DATABASE db_market_data'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'db_market_data')\gexec
