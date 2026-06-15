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
-- db_execution: durable order store for the Execution engine
-- (feature-execution-engine Phase 1). A dedicated database (not a schema in
-- db_gateway) keeps the order store independently owned, mirroring
-- db_market_data; the standalone quant-execution-engine becomes the sole
-- writer in Phase 2.
SELECT 'CREATE DATABASE db_execution'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'db_execution')\gexec
-- db_orderbook: durable hot-tier order-book capture store for the Order-Book
-- Capture engine (feature-orderbook-engine Phase 1). A dedicated database (not
-- a schema in db_gateway) keeps the capture store independently owned,
-- mirroring db_market_data / db_execution; the standalone
-- quant-orderbook-engine (market-data plane, host :8600) becomes the sole
-- writer. The append-only binary raw log + Parquet cold tier are the systems
-- of record; this DB is the regenerable queryable mirror.
SELECT 'CREATE DATABASE db_orderbook'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'db_orderbook')\gexec
