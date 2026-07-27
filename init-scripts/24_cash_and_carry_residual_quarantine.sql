-- ============================================================================
-- 24_cash_and_carry_residual_quarantine.sql
-- ----------------------------------------------------------------------------
-- Additive B3 (close-path) migration for the cash-and-carry SET<->TFEX arb
-- store (strategies/cash-and-carry-set-tfex, host :8110; TK-0131 Part B).
-- Two strictly-additive changes to arb_trades (base schema:
-- 23_schema_db_cash_and_carry_set_tfex.sql), landed + verified INERT before any
-- consuming code ships (so the running pre-B3 strategy provably tolerates them):
--
--   1. residual_stock_qty / residual_ssf_qty  — a partial two-leg close can leave
--      a leg unhedged (the SSF is atomic at 1 contract; the divisible stock leg
--      can partial). ONE nullable INT per leg (NOT a leg-discriminator + a single
--      qty) so a *double* residual — both legs short after a walk — is expressible
--      without a lossy workaround; NULL == that leg fully closed. Derivable from
--      arb_orders fills, but explicit columns make the loop-block query + the
--      resolver state clean. `arb_trades` is the transactional system-of-record,
--      so this DDL is infra-db-owned (NOT the strategy's — unlike the regenerable
--      arb_shadow analysis table's deliberate CREATE-IF-NOT-EXISTS deviation).
--
--   2. 'QUARANTINED' status — a NEW terminal status for DEPLOY-GATE Q: the
--      pre-close-regime OPEN rows (phantom ex-div/stacking artifacts + stale
--      multi-day holds that never had a close path) are marked QUARANTINED
--      immediately before EOD-flatten goes live so its first run starts from a
--      clean slate WITHOUT routing ~20 identical closes through PTRM's burst
--      guard or banking phantom realized loss. Audited safe: every existing
--      status predicate is positive equality/FILTER (read_open_positions /
--      open_pairs_eod `='OPEN'`; aggregate.py FILTER on CLOSED|ABORTED|UNWOUND)
--      — ZERO `!= 'OPEN'` — so a brand-new status is invisible to all of them.
--
-- Conventions (inherited from 23_* and 13_execution_strategy_id.sql):
--   * Strictly additive: two nullable columns (no DEFAULT -> catalog-only
--     ADD COLUMN, no table rewrite) + a superset CHECK. Rows written before the
--     columns exist stay NULL; engine builds that predate them never read them.
--   * Fully idempotent: ADD COLUMN IF NOT EXISTS + DROP CONSTRAINT IF EXISTS /
--     ADD CONSTRAINT — safe under container init re-run AND live re-apply. On a
--     fresh DB, 23_* creates arb_trades first, then this converges it.
--   * Live apply is off-market / lunch-window only (arb_trades is written every
--     ~2 s; ADD COLUMN + the CHECK swaps each take a brief ACCESS EXCLUSIVE
--     lock). The superset status CHECK validates all existing rows (their
--     statuses are a subset of the new list), so ADD never fails on live data.
--
-- Rollback:
--   ALTER TABLE arb_trades DROP CONSTRAINT IF EXISTS arb_trades_residual_stock_check;
--   ALTER TABLE arb_trades DROP CONSTRAINT IF EXISTS arb_trades_residual_ssf_check;
--   ALTER TABLE arb_trades DROP COLUMN IF EXISTS residual_stock_qty;
--   ALTER TABLE arb_trades DROP COLUMN IF EXISTS residual_ssf_qty;
--   ALTER TABLE arb_trades DROP CONSTRAINT IF EXISTS arb_trades_status_check;
--   ALTER TABLE arb_trades ADD CONSTRAINT arb_trades_status_check
--       CHECK (status IN ('PENDING','OPEN','CLOSED','UNWOUND','ABORTED'));
--   (rollback requires 0 rows in status='QUARANTINED' or the readd will fail.)
-- ============================================================================

\connect db_cash_and_carry_set_tfex

-- 1. per-leg residual quantity (B3 close-path partial-hedge state) ------------
-- NULL == that leg fully closed; a value == the unhedged remainder on that leg.
-- Independent per leg so a double residual (both short) is expressible.
ALTER TABLE arb_trades ADD COLUMN IF NOT EXISTS residual_stock_qty INTEGER;
ALTER TABLE arb_trades ADD COLUMN IF NOT EXISTS residual_ssf_qty INTEGER;

ALTER TABLE arb_trades DROP CONSTRAINT IF EXISTS arb_trades_residual_stock_check;
ALTER TABLE arb_trades ADD CONSTRAINT arb_trades_residual_stock_check
    CHECK (residual_stock_qty IS NULL OR residual_stock_qty > 0);

ALTER TABLE arb_trades DROP CONSTRAINT IF EXISTS arb_trades_residual_ssf_check;
ALTER TABLE arb_trades ADD CONSTRAINT arb_trades_residual_ssf_check
    CHECK (residual_ssf_qty IS NULL OR residual_ssf_qty > 0);

-- 2. extend the status CHECK to allow the new terminal 'QUARANTINED' ----------
-- (superset of the old list -> validates cleanly against all existing rows).
ALTER TABLE arb_trades DROP CONSTRAINT IF EXISTS arb_trades_status_check;
ALTER TABLE arb_trades ADD CONSTRAINT arb_trades_status_check
    CHECK (status IN ('PENDING', 'OPEN', 'CLOSED', 'UNWOUND', 'ABORTED', 'QUARANTINED'));
