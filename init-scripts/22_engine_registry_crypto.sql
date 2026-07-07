\c db_gateway

-- feature-crypto-engine Phase 4: register the crypto capture engine as a
-- gateway-proxied EXTERNAL engine so the gateway's DB-backed /api/v2/engines/catalog
-- lists it. 07_engine_catalog.sql seeds the base engines but only runs on FIRST
-- provision; an already-provisioned db_gateway needs this numbered migration to
-- insert the crypto row. ON CONFLICT keeps it a safe no-op when 07 already did
-- (fresh provisions) or when this migration is re-applied (idempotent).
INSERT INTO engine_registry (slug, type, status, description) VALUES
  ('crypto',      'EXTERNAL', 'active',  'Standalone quant-crypto-engine (host :9100), gateway-proxied; durable 24/7 crypto L2/T&S capture — Binance TH/Global + Bitkub (read-only, market-data plane)')
ON CONFLICT (slug) DO NOTHING;
