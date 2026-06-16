-- ============================================================================
-- 15_orderbook_greeks.sql
-- ----------------------------------------------------------------------------
-- Derived EOD Black-76 implied volatility and Greeks for TFEX SET50 options.
-- One row per (date, option-symbol); freely regenerable from
-- ``orderbook.settlements`` (the settlement anchor) and the raw captured data.
--
-- Design:
--   * This is a DERIVED, low-cardinality reference table (one option × one
--     expiry per trading day) — a PLAIN table, not a hypertable, mirroring
--     the ``orderbook.settlements`` profile.
--   * ``forward`` is the same-series futures settlement price used as the
--     Black-76 forward; ``option_price`` is the option settlement price used
--     as the market price input to the IV solver.
--   * ``iv`` is nullable (NULL when the solver cannot converge, e.g. below-
--     intrinsic or zero-premium options). All Greeks columns are likewise
--     nullable — downstream consumers must handle NULL.
--   * ``time_to_expiry`` is stored in years (calendar-day fraction); its
--     exact calculation (ACT/365 vs ACT/252) is a caller concern, so no CHECK
--     constraint forces positivity — it may be zero on expiry day.
--   * ``source`` records the pricing model used; default 'black76'.
--   * PK = (date, symbol) gives idempotent ON CONFLICT upsert (re-running the
--     EOD greeks computation is always safe).
--
-- Rollback: ``DROP TABLE IF EXISTS orderbook.greeks;``
-- ============================================================================

\connect db_orderbook

-- ---------------------------------------------------------------------------
-- orderbook.greeks — derived EOD Black-76 IV and Greeks for TFEX SET50 options
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orderbook.greeks (
    date               DATE           NOT NULL,
    symbol             TEXT           NOT NULL,   -- e.g. S50M26C1000
    series             TEXT           NOT NULL,   -- e.g. M26
    is_call            BOOLEAN        NOT NULL,
    strike             NUMERIC(18, 6) NOT NULL CHECK (strike > 0),
    underlying_symbol  TEXT           NOT NULL,   -- same-series futures used as Black-76 forward
    forward            NUMERIC(18, 6) NOT NULL CHECK (forward > 0),
    option_price       NUMERIC(18, 6) NOT NULL CHECK (option_price > 0),
    time_to_expiry     NUMERIC,                   -- years; nullable (zero on expiry day)
    iv                 NUMERIC,                   -- implied vol; NULL when unsolvable/below-intrinsic
    delta              NUMERIC,
    gamma              NUMERIC,
    vega               NUMERIC,
    theta              NUMERIC,
    rate               NUMERIC,                   -- risk-free rate used
    source             TEXT           NOT NULL DEFAULT 'black76',
    CONSTRAINT pk_greeks PRIMARY KEY (date, symbol)
);

-- Read path: "all greeks for one option symbol, newest first".
CREATE INDEX IF NOT EXISTS ix_greeks_symbol_date
    ON orderbook.greeks (symbol, date DESC);

-- ---------------------------------------------------------------------------
-- Grants — the quant role needs SELECT/INSERT/UPDATE for idempotent upserts.
-- This grant lives here (not in 14_schema_orderbook.sql) because the table
-- did not exist when 14's grant block ran.
-- ---------------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE ON orderbook.greeks TO quant;
