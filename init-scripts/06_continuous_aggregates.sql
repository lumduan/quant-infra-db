-- =============================================================================
-- 06_continuous_aggregates.sql
-- =============================================================================
-- Purpose: Strategies-Report-Metrics — Phase 2 TimescaleDB continuous
-- aggregates (monthly roll-ups) and their refresh policies.
--   * db_csm_set:  cagg_trade_history_monthly  — wins / losses / net_pnl
--   * db_gateway:  cagg_daily_performance_monthly — avg return / drawdown / EOM value
--
-- Order dependency: must run after 05_schema_strategy_report.sql. The view
-- on db_csm_set references trade_history.realized_pnl (added in 05); the
-- view on db_gateway aggregates daily_performance (created in 04).
--
-- Idempotency: CREATE MATERIALIZED VIEW IF NOT EXISTS guards the views;
-- add_continuous_aggregate_policy(..., if_not_exists => TRUE) guards the
-- refresh jobs. "WITH NO DATA" defers the initial materialization to the
-- first scheduled refresh — needed because the source tables may be empty
-- on a fresh container boot.
-- =============================================================================

\c db_csm_set

CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_trade_history_monthly
WITH (timescaledb.continuous) AS
SELECT strategy_id,
       time_bucket(INTERVAL '1 month', time)        AS bucket,
       count(*) FILTER (WHERE realized_pnl > 0)     AS wins,
       count(*) FILTER (WHERE realized_pnl < 0)     AS losses,
       coalesce(sum(realized_pnl), 0)               AS net_pnl
FROM trade_history
WHERE realized_pnl IS NOT NULL
GROUP BY strategy_id, bucket
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'cagg_trade_history_monthly',
    start_offset      => INTERVAL '12 months',
    end_offset        => INTERVAL '2 hours',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE
);

\c db_gateway

CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_daily_performance_monthly
WITH (timescaledb.continuous) AS
SELECT strategy_id,
       time_bucket(INTERVAL '1 month', time) AS bucket,
       avg(daily_return)                     AS avg_daily_return,
       min(max_drawdown)                     AS worst_max_drawdown,
       last(total_value, time)               AS month_end_value
FROM daily_performance
GROUP BY strategy_id, bucket
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'cagg_daily_performance_monthly',
    start_offset      => INTERVAL '6 months',
    end_offset        => INTERVAL '2 hours',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE
);
