\c db_gateway

CREATE TABLE IF NOT EXISTS engine_registry (
    id          SERIAL PRIMARY KEY,
    slug        TEXT UNIQUE NOT NULL,
    type        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO engine_registry (slug, type, status, description) VALUES
  ('market-data', 'EXTERNAL', 'active',  'Wraps settfex + tvkit for OHLCV/data fetching'),
  ('backtest',    'EXTERNAL', 'active',  'Wraps csm-set walk-forward backtesting'),
  ('portfolio',   'INTERNAL', 'active',  'Aggregation, snapshots, equity curves, strategy reports'),
  ('signals',     'EXTERNAL', 'dormant', 'Signal generation pipeline (future)'),
  -- feature-execution-engine Phase 2: canonical order router (host :8400),
  -- gateway-proxied; sim-first, no broker credential in the gateway.
  ('execution',   'EXTERNAL', 'active',  'Standalone quant-execution-engine (host :8400), gateway-proxied; canonical order router (sim-first), no broker credential in the gateway')
ON CONFLICT (slug) DO NOTHING;
