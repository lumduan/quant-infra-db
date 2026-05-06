-- Idempotent database creation. PostgreSQL does not support
-- CREATE DATABASE IF NOT EXISTS, so we use psql's \gexec to
-- conditionally execute CREATE only when the database is absent.
SELECT 'CREATE DATABASE db_csm_set'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'db_csm_set')\gexec
SELECT 'CREATE DATABASE db_gateway'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'db_gateway')\gexec
