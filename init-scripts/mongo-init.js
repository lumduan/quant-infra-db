// MongoDB init script — csm_logs database
// =============================================================================
// Runs automatically on first container start via /docker-entrypoint-initdb.d/.
// Docker only executes *.js files in this directory when the MongoDB data volume
// is empty, so this script is effectively idempotent.  Additionally, every
// operation below uses idempotent commands:
//   - createCollection() is a no-op if the collection already exists.
//   - createIndex()  is a no-op if an identical index already exists.
//
// Database: csm_logs
//   Stores schema-less operational data for the CSM-SET strategy:
//     backtest_results  — historical backtest run outputs (equity curves, metrics)
//     model_params      — serialized model hyperparameters keyed by version
//     signal_snapshots  — daily signal vectors per strategy
// =============================================================================

db = db.getSiblingDB('csm_logs');

// ---------------------------------------------------------------------------
// Collections
// ---------------------------------------------------------------------------

// Each backtest run produces one document containing equity curves,
// summary statistics, and configuration metadata.
//
// As of the Strategies-Report-Metrics feature (Phase 2), csm-set writes
// the following additional keys into each `backtest_results` document
// (no schema change — MongoDB is schema-less so these land automatically):
//   metrics.headline               — total_pnl, profit_factor, total_trades, …
//   metrics.profit_structure       — gross_profit, gross_loss, …
//   metrics.returns                — { all, long, short } daily/monthly returns
//   metrics.benchmark_comparison   — alpha, beta vs buy-and-hold benchmark
//   metrics.risk_adjusted          — sharpe, sortino, calmar, …
//   metrics.pnl_distribution       — histogram buckets
//   metrics.trades_analysis        — winners/losers, avg holding bars
//   metrics.capital_efficiency     — margin usage, capital_used
//   metrics.runups_drawdowns       — top N run-up + drawdown windows
// The matching Pydantic schema lives in quant-api-gateway (Phase 3).
db.createCollection('backtest_results');

// Model hyperparameter sets are versioned so that every backtest can
// reference the exact parameter snapshot used.
db.createCollection('model_params');

// Signal snapshots capture per-strategy signal vectors for a given date.
// Downstream consumers query by (strategy_id, date) to replay signals.
db.createCollection('signal_snapshots');

// ---------------------------------------------------------------------------
// Indexes
// ---------------------------------------------------------------------------

// Look up backtest results for a strategy, newest first.
db.backtest_results.createIndex({ strategy_id: 1, created_at: -1 });

// Look up the latest version of model parameters for a strategy.
db.model_params.createIndex({ strategy_id: 1, version: -1 });

// Look up signal snapshots for a strategy on a specific date.
db.signal_snapshots.createIndex({ strategy_id: 1, date: -1 });
