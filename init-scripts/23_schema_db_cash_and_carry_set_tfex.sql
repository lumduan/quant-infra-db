\c db_cash_and_carry_set_tfex

-- Strategy-private store for the SET<->TFEX single-stock-futures cash-and-carry
-- (basis) arbitrage strategy (`cash-and-carry-set-tfex`, host :8110). A dedicated
-- database (mirroring db_csm_set / db_tfex_s50_multi_tf_swing) so the strategy's
-- per-decision / per-leg statistics are independently owned; the gateway remains the
-- sole writer to db_gateway (this strategy POSTs its daily report over HTTP, never
-- connecting to db_gateway directly). Schema per plans/cash-and-carry-set-tfex/SCHEMAS.md.
-- Money NUMERIC(18,4); fractional percentages NUMERIC(8,4); timestamps TIMESTAMPTZ (UTC);
-- UNIQUE natural keys for idempotent UPSERT. Append-only capture-first semantics.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- arb_decisions: every basis evaluation, banked capture-first (ADR CA1/CA4/CA8).
-- TimescaleDB hypertable on ts_decision; the unique index includes the partition
-- column (TimescaleDB requirement). `id` is a surrogate identity column (not PK —
-- a hypertable PK must include the partition key).
CREATE TABLE IF NOT EXISTS arb_decisions (
    id             BIGINT GENERATED ALWAYS AS IDENTITY,
    ts_decision    TIMESTAMPTZ   NOT NULL,
    ssf_symbol     TEXT          NOT NULL,
    underlying     TEXT          NOT NULL,
    dte            INTEGER       NOT NULL,
    stock_bid      NUMERIC(18,4),
    stock_ask      NUMERIC(18,4),
    fut_bid        NUMERIC(18,4),
    fut_ask        NUMERIC(18,4),
    quote_age_ms   INTEGER       NOT NULL,
    quote_source   TEXT          NOT NULL,   -- capture | bridge_poll (CA7 rung)
    raw_basis_thb  NUMERIC(18,4) NOT NULL,
    fair_gap_thb   NUMERIC(18,4),            -- CA1: banked, never decides
    gross_thb      NUMERIC(18,4) NOT NULL,
    cost_thb       NUMERIC(18,4) NOT NULL,
    net_thb        NUMERIC(18,4) NOT NULL,
    net_bps        NUMERIC(8,4)  NOT NULL,
    threshold_pass BOOLEAN       NOT NULL,
    action         TEXT          NOT NULL CHECK (action IN ('ENTER', 'SKIP', 'ABORT')),
    skip_reason    TEXT,
    book_snapshot  JSONB         NOT NULL,   -- CA4: top-5 depth, BOTH legs
    CONSTRAINT uq_arb_decisions_ts_symbol UNIQUE (ts_decision, ssf_symbol)
);
SELECT create_hypertable('arb_decisions', 'ts_decision', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_arb_decisions_symbol_ts
    ON arb_decisions (ssf_symbol, ts_decision DESC);
CREATE INDEX IF NOT EXISTS idx_arb_decisions_action_ts
    ON arb_decisions (action, ts_decision DESC);

-- arb_trades: one row per two-leg arb attempt (plain table).
CREATE TABLE IF NOT EXISTS arb_trades (
    trade_id            UUID PRIMARY KEY,
    decision_ts         TIMESTAMPTZ NOT NULL,
    ssf_symbol          TEXT        NOT NULL,
    underlying          TEXT        NOT NULL,
    ts_open             TIMESTAMPTZ NOT NULL,
    ts_closed           TIMESTAMPTZ,
    status              TEXT        NOT NULL
        CHECK (status IN ('PENDING', 'OPEN', 'CLOSED', 'UNWOUND', 'ABORTED')),
    contracts           INTEGER     NOT NULL,
    target_net_thb      NUMERIC(18,4) NOT NULL,
    realized_gross_thb  NUMERIC(18,4),
    commission_thb      NUMERIC(18,4),
    realized_net_thb    NUMERIC(18,4),
    spread_captured_pct NUMERIC(8,4),
    orders_per_trade    INTEGER     NOT NULL DEFAULT 0,
    leg_risk_window_ms  INTEGER,
    unwind_reason       TEXT
);
CREATE INDEX IF NOT EXISTS idx_arb_trades_status ON arb_trades (status);
CREATE INDEX IF NOT EXISTS idx_arb_trades_symbol_open ON arb_trades (ssf_symbol, ts_open DESC);

-- arb_orders: one row per leg order (per-leg speed/slippage stats; plain table).
-- client_order_id is the engine idempotency key (UUIDv4). trade_id FKs arb_trades
-- (a plain table — a hypertable cannot be an FK target).
CREATE TABLE IF NOT EXISTS arb_orders (
    order_id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_id            UUID          NOT NULL REFERENCES arb_trades (trade_id),
    client_order_id     UUID          NOT NULL UNIQUE,
    leg                 TEXT          NOT NULL CHECK (leg IN ('STOCK', 'SSF')),
    intent              TEXT          NOT NULL
        CHECK (intent IN ('ENTRY', 'EXIT', 'COMPLETE_RETRY', 'UNWIND')),
    side                TEXT          NOT NULL,
    qty                 INTEGER       NOT NULL,
    limit_price         NUMERIC(18,4) NOT NULL,
    fill_price          NUMERIC(18,4),
    fill_qty            INTEGER,
    ts_decision         TIMESTAMPTZ   NOT NULL,
    ts_submit           TIMESTAMPTZ   NOT NULL,
    ts_ack              TIMESTAMPTZ,
    ts_first_fill       TIMESTAMPTZ,       -- from SSE, never the POST ack
    ts_terminal         TIMESTAMPTZ,
    decision_to_ack_ms  INTEGER,
    ack_to_fill_ms      INTEGER,
    decision_to_fill_ms INTEGER,
    slippage_thb        NUMERIC(18,4),
    status              TEXT          NOT NULL,
    reject_reason       TEXT
);
CREATE INDEX IF NOT EXISTS idx_arb_orders_trade ON arb_orders (trade_id);
CREATE INDEX IF NOT EXISTS idx_arb_orders_leg ON arb_orders (leg);

-- arb_missed: opportunities not taken (the improvement gold-mine; plain table).
CREATE TABLE IF NOT EXISTS arb_missed (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts            TIMESTAMPTZ   NOT NULL,
    ssf_symbol    TEXT          NOT NULL,
    net_thb       NUMERIC(18,4) NOT NULL,
    reason        TEXT          NOT NULL CHECK (reason IN (
        'NO_QUOTE', 'STALE_QUOTE', 'WIDE_BOOK', 'THIN_BOOK', 'BALANCE', 'MARGIN',
        'HALT', 'LEG_TIMEOUT', 'THROTTLE', 'DTE', 'CA_WINDOW', 'PAIR_BUSY',
        'GLOBAL_CAP', 'SESSION')),
    book_snapshot JSONB         NOT NULL,
    CONSTRAINT uq_arb_missed_ts_symbol_reason UNIQUE (ts, ssf_symbol, reason)
);
CREATE INDEX IF NOT EXISTS idx_arb_missed_reason_ts ON arb_missed (reason, ts DESC);

-- arb_daily: EOD rollup (source of the daily gateway report; plain table).
CREATE TABLE IF NOT EXISTS arb_daily (
    date                       DATE PRIMARY KEY,   -- Asia/Bangkok trading day
    opportunities              INTEGER NOT NULL,
    entered                    INTEGER NOT NULL,
    both_filled                INTEGER NOT NULL,
    one_leg_incidents          INTEGER NOT NULL,
    auto_unwinds               INTEGER NOT NULL,
    orders                     INTEGER NOT NULL,
    gross_thb                  NUMERIC(18,4) NOT NULL,
    costs_thb                  NUMERIC(18,4) NOT NULL,
    net_thb                    NUMERIC(18,4) NOT NULL,
    median_decision_to_fill_ms INTEGER,
    p95_leg_window_ms          INTEGER,
    fill_ratio_upper_bound     NUMERIC(8,4),       -- CA4 caveat: sim always fills
    missed_count               INTEGER NOT NULL,
    universe_pairs_enabled     INTEGER NOT NULL
);
