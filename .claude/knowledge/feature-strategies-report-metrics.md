# Feature notes — Strategies Report Metrics (Phase 2)

Captured during the Phase 2 implementation
(branch `feat/schema-hypertables-continuous-aggregates`, 2026-05-21).
These notes are non-obvious from the code and may save the next contributor
some live-stack debugging.

## TimescaleDB continuous-aggregate gotchas

1. **A continuous aggregate's source table must already be a hypertable.**
   The PostgreSQL error `invalid continuous aggregate view / At least one
   hypertable should be used in the view definition` looks like a SQL
   validation error but is really a "missing prerequisite" — convert the
   source table with `create_hypertable(...)` first.

2. **Hypertables require the partitioning column to be part of every UNIQUE
   constraint, including the PRIMARY KEY.** `trade_history` originally had
   `id SERIAL PRIMARY KEY`. Before `create_hypertable('trade_history', 'time')`
   could succeed we had to widen the PK to `(id, time)`. The idempotent guard
   used in `05_schema_strategy_report.sql` is:
   ```sql
   DO $$
   BEGIN
       IF NOT EXISTS (
           SELECT 1 FROM timescaledb_information.hypertables
           WHERE hypertable_name = 'trade_history'
       ) THEN
           ALTER TABLE trade_history DROP CONSTRAINT IF EXISTS trade_history_pkey;
           ALTER TABLE trade_history ADD CONSTRAINT trade_history_pkey PRIMARY KEY (id, time);
           PERFORM create_hypertable(
               'trade_history', 'time',
               migrate_data => TRUE,
               if_not_exists => TRUE
           );
       END IF;
   END
   $$;
   ```
   `migrate_data => TRUE` is required when the table already contains rows.

3. **`CREATE MATERIALIZED VIEW IF NOT EXISTS … WITH (timescaledb.continuous)`
   is supported in TimescaleDB 2.x** and is the idempotent way to declare a
   continuous aggregate. No `DO $$ … EXCEPTION` wrapper is needed for the
   view itself.

4. **`add_continuous_aggregate_policy(...)` accepts `if_not_exists => TRUE`**
   for idempotent re-runs. A second run logs a NOTICE and returns `-1`
   instead of raising. This is the documented behavior; do not wrap it in
   an exception handler.

5. **`WITH NO DATA` on the materialized-view body** defers the initial
   materialization. Use this when the source hypertable may be empty on
   first boot (no rows in `daily_performance` / `trade_history` yet) so
   the boot-time refresh doesn't fail.

## Idempotency pattern for relaxed CHECK constraints

The Phase 2 ROADMAP needed `trade_history.side` to accept a broader set of
values. The constraint did not exist on disk, so a naïve `ALTER TABLE … ADD
CONSTRAINT …` would fail on the second run with `constraint already exists`.
The idempotent pattern is:

```sql
ALTER TABLE trade_history
    DROP CONSTRAINT IF EXISTS trade_history_side_check;
ALTER TABLE trade_history
    ADD CONSTRAINT trade_history_side_check
        CHECK (side IN ('LONG','SHORT','BUY','SELL','HOLD'));
```

DROP-then-ADD is safe regardless of starting state because the broader value
set is a superset of any plausible legacy `side` value (so the new check
never rejects existing rows).

## Numeric vs double precision

The project rule "monetary values are `Decimal` at the gateway boundary;
never `float`" applies to **new** columns. The Phase 2 columns
(`entry_price`, `exit_price`, `realized_pnl`, `equity` on
`benchmark_equity_curve`) are `NUMERIC(18,4)` and round-trip cleanly through
asyncpg as Python `Decimal`. Legacy columns
(`equity_curve.equity`, `trade_history.price/quantity/commission`,
`daily_performance.*`) remain `DOUBLE PRECISION` — migrating them would be
a separate, invasive change requiring coordination with the csm-set adapter
and is explicitly out of scope here.

## Pre-existing infra-test failures (unrelated to Phase 2)

`tests/test_mongo.py::test_collections_exist`, `test_indexes_exist`,
`test_document_round_trip` fail when run with `pytest -m infra` because the
default `mongosh` connection has no auth credentials but the running
container requires authentication. This is a pre-existing environment
issue, not a Phase 2 regression. The postgres-side infra tests (the ones
this phase added and extended) all pass.
