-- ============================================================================
-- 13_execution_strategy_id.sql
-- ----------------------------------------------------------------------------
-- Additive Phase-5 column for the Execution engine order store
-- (feature-execution-engine, Phase 5 — strategy execution path + order-update
-- streaming). The engine stamps the submitting strategy's identity (an
-- ``X-Strategy-Id`` request header, NOT a field of the frozen NormalizedOrder
-- contract) onto the order row so the order-update stream
-- (``GET /orders/stream?strategy_id=...``) can filter durably — including
-- reconciler-driven events for orders submitted before an engine restart.
--
-- Conventions (inherited from 12_schema_execution.sql):
--   * Strictly additive: a nullable TEXT column + one partial index. No
--     trigger change, no edge change, no CHECK on the value (the id is an
--     opaque strategy slug, validated at the engine boundary like
--     client_order_id per ADR §A discipline). Engine builds that predate the
--     column never read it; rows written before it exists stay NULL.
--   * Fully idempotent: ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS
--     — safe under container init re-run AND live re-apply.
--   * Grants: the existing table-level GRANTs on execution.orders (12_*)
--     already cover new columns; nothing to add.
--
-- Rollback: ALTER TABLE execution.orders DROP COLUMN IF EXISTS strategy_id;
--           (drops idx_orders_strategy with it).
-- ============================================================================

\connect db_execution

ALTER TABLE execution.orders ADD COLUMN IF NOT EXISTS strategy_id TEXT;

-- Stream-filter seed path: "all (recent) orders for one strategy". Partial —
-- strategy-less rows (direct/operator submits, pre-Phase-5 rows) stay out.
CREATE INDEX IF NOT EXISTS idx_orders_strategy
    ON execution.orders (strategy_id, created_at)
    WHERE strategy_id IS NOT NULL;
