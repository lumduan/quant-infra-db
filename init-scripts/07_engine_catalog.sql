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
  ('execution',   'EXTERNAL', 'active',  'Standalone quant-execution-engine (host :8400), gateway-proxied; canonical order router (sim-first), no broker credential in the gateway'),
  -- feature-orderbook-engine Phase 4 §4.1: durable L2/T&S capture + derived
  -- greeks/features (host :8600), gateway-proxied; read-only market-data plane.
  ('orderbook',   'EXTERNAL', 'active',  'Standalone quant-orderbook-engine (host :8600), gateway-proxied; durable L2/T&S capture + derived greeks/features (read-only, market-data plane)'),
  -- feature-crypto-engine Phase 4: durable 24/7 crypto L2/T&S capture (host :9100),
  -- gateway-proxied; read-only market-data plane (Binance TH/Global + Bitkub).
  ('crypto',      'EXTERNAL', 'active',  'Standalone quant-crypto-engine (host :9100), gateway-proxied; durable 24/7 crypto L2/T&S capture — Binance TH/Global + Bitkub (read-only, market-data plane)')
ON CONFLICT (slug) DO NOTHING;
