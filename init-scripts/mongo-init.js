// MongoDB init script for csm_logs database
// Runs on first container start via /docker-entrypoint-initdb.d/

db = db.getSiblingDB('csm_logs');

// Collections
db.createCollection('backtest_results');
db.createCollection('model_params');
db.createCollection('signal_snapshots');

// Indexes
db.backtest_results.createIndex({ strategy_id: 1, created_at: -1 });
db.model_params.createIndex({ strategy_id: 1, created_at: -1 });
db.signal_snapshots.createIndex({ strategy_id: 1, created_at: -1 });
