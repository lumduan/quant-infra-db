-- ============================================================================
-- 25_execution_broker_streaming_pro.sql
-- ----------------------------------------------------------------------------
-- Correct `execution.orders.broker`'s CHECK to the brokers that actually exist.
--
-- 12_schema_execution.sql:87-88 pins the value set frozen at Phase 0:
--     CHECK (broker IN ('sim', 'liberator', 'settrade'))
--
-- `settrade` (InnovestX broker-023 / the Settrade Open API) was REMOVED from the
-- engine on 2026-07-18 — quant-execution-engine PR #25, `d920c38`, Option B:
-- the SettradeAdapter, its order-book provider, its config and the settrade-v2
-- dependency all deleted — and `streaming_pro` (the self-built retail bridge)
-- replaced it. The CHECK was never updated, in this repo or in either live
-- database.
--
-- CONSEQUENCE, measured on live infrastructure 2026-08-21 at STAGE=paper with a
-- matched control (same order shape; only `broker` differed):
--     broker=liberator      -> FILLED
--     broker=streaming_pro  -> asyncpg CheckViolationError (23514), HTTP 500
-- The insert is the FIRST write in the submit path (core/router.py:171, before
-- adapter.place at :189), so a streaming_pro order dies before the stage gate's
-- paper-intercept is even reached.
--
-- 🔴 It surfaces as an UNTYPED 500, not a typed rejection envelope. A calling
-- strategy classifies bare 5xx as RETRYABLE and resends the same
-- client_order_id — so the first real Streaming Pro order presents as a
-- transient network fault and retries, rather than as the permanent config
-- error it is. That is why this is worth fixing before micro_live rather than
-- discovering it there.
--
-- Invisible until now because every order ever written is broker='sim'
-- (feature-execution-ha EH6 measured 200/200 on 2026-08-14).
--
-- Conventions (following the 13_execution_strategy_id.sql precedent):
--   * A separate numbered script rather than an edit to 12_*: init scripts run
--     in filename order, so a FRESH volume applies 12 then this, and an EXISTING
--     database gets it by re-apply. Both converge on the same constraint.
--   * Idempotent: DROP ... IF EXISTS then ADD — safe under container init re-run
--     AND live re-apply.
--   * No data migration. Verified 2026-08-21 on BOTH nodes before writing this:
--         HOME db_execution : sim=276,             settrade=0
--         AWS  db_execution : sim=1, liberator=2,  settrade=0
--     Zero rows hold 'settrade', so dropping it from the allowed set cannot
--     orphan a row. ⚠️ If that is ever untrue on some other deployment, this
--     script FAILS LOUDLY at ADD CONSTRAINT rather than silently — which is the
--     correct behaviour, not a defect to work around.
--
-- Rollback:
--     ALTER TABLE execution.orders DROP CONSTRAINT IF EXISTS orders_broker_check;
--     ALTER TABLE execution.orders ADD CONSTRAINT orders_broker_check
--         CHECK (broker IN ('sim', 'liberator', 'settrade'));
-- ============================================================================

\connect db_execution

ALTER TABLE execution.orders DROP CONSTRAINT IF EXISTS orders_broker_check;

ALTER TABLE execution.orders ADD CONSTRAINT orders_broker_check
    CHECK (broker IN ('sim', 'liberator', 'streaming_pro'));
