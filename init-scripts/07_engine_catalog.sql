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
  ('signals',     'EXTERNAL', 'dormant', 'Signal generation pipeline (future)')
ON CONFLICT (slug) DO NOTHING;
