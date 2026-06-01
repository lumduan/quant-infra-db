import pytest
from src.config import Settings

pytestmark = pytest.mark.infra


@pytest.fixture
def settings() -> Settings:
    """Load settings from the real .env file (requires .env with valid POSTGRES_PASSWORD)."""
    return Settings()


async def test_connect_to_csm_set(settings: Settings) -> None:
    """Connect to db_csm_set and run SELECT 1."""
    import asyncpg

    conn = await asyncpg.connect(settings.csm_set_dsn)
    try:
        result = await conn.fetchval("SELECT 1")
        assert result == 1
    finally:
        await conn.close()


async def test_connect_to_gateway(settings: Settings) -> None:
    """Connect to db_gateway and run SELECT 1."""
    import asyncpg

    conn = await asyncpg.connect(settings.gateway_dsn)
    try:
        result = await conn.fetchval("SELECT 1")
        assert result == 1
    finally:
        await conn.close()


async def test_timescaledb_extension_present(settings: Settings) -> None:
    """TimescaleDB extension must be active in both databases."""
    import asyncpg

    for dsn in (settings.csm_set_dsn, settings.gateway_dsn):
        conn = await asyncpg.connect(dsn)
        try:
            row = await conn.fetchrow(
                "SELECT extname, extversion FROM pg_extension WHERE extname = 'timescaledb'"
            )
            assert row is not None, f"TimescaleDB not found in {dsn.split('/')[-1]}"
            assert row["extname"] == "timescaledb"
        finally:
            await conn.close()


async def test_hypertables_exist(settings: Settings) -> None:
    """Expected hypertables must exist (including Phase 2 additions)."""
    import asyncpg

    conn = await asyncpg.connect(settings.csm_set_dsn)
    try:
        rows = await conn.fetch("SELECT hypertable_name FROM timescaledb_information.hypertables")
        hypertables = {r["hypertable_name"] for r in rows}
        assert "equity_curve" in hypertables
        assert "benchmark_equity_curve" in hypertables
    finally:
        await conn.close()

    conn = await asyncpg.connect(settings.gateway_dsn)
    try:
        rows = await conn.fetch("SELECT hypertable_name FROM timescaledb_information.hypertables")
        hypertables = {r["hypertable_name"] for r in rows}
        assert "daily_performance" in hypertables
        assert "portfolio_snapshot" in hypertables
        assert "strategy_report_snapshot" in hypertables
    finally:
        await conn.close()


async def test_continuous_aggregates_registered(settings: Settings) -> None:
    """Phase 2 continuous aggregates must be visible in TimescaleDB metadata."""
    import asyncpg

    conn = await asyncpg.connect(settings.csm_set_dsn)
    try:
        rows = await conn.fetch(
            "SELECT view_name FROM timescaledb_information.continuous_aggregates"
        )
        views = {r["view_name"] for r in rows}
        assert "cagg_trade_history_monthly" in views
    finally:
        await conn.close()

    conn = await asyncpg.connect(settings.gateway_dsn)
    try:
        rows = await conn.fetch(
            "SELECT view_name FROM timescaledb_information.continuous_aggregates"
        )
        views = {r["view_name"] for r in rows}
        assert "cagg_daily_performance_monthly" in views
    finally:
        await conn.close()


async def test_trade_history_phase2_columns_present(settings: Settings) -> None:
    """trade_history must have the four Phase 2 P&L columns and the relaxed side CHECK."""
    import asyncpg

    conn = await asyncpg.connect(settings.csm_set_dsn)
    try:
        rows = await conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'trade_history' AND table_schema = 'public'"
        )
        cols = {r["column_name"]: r["data_type"] for r in rows}
        assert cols.get("entry_price") == "numeric"
        assert cols.get("exit_price") == "numeric"
        assert cols.get("realized_pnl") == "numeric"
        assert cols.get("duration_bars") == "integer"

        constraint = await conn.fetchval(
            "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "WHERE t.relname = 'trade_history' AND c.conname = 'trade_history_side_check'"
        )
        assert constraint is not None
        for token in ("'LONG'", "'SHORT'", "'BUY'", "'SELL'", "'HOLD'"):
            assert token in constraint
    finally:
        await conn.close()


async def test_strategy_report_snapshot_columns(settings: Settings) -> None:
    """strategy_report_snapshot must have time/strategy_id/report/computed_at."""
    import asyncpg

    conn = await asyncpg.connect(settings.gateway_dsn)
    try:
        rows = await conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'strategy_report_snapshot' AND table_schema = 'public'"
        )
        cols = {r["column_name"]: r["data_type"] for r in rows}
        assert cols.get("time") == "timestamp with time zone"
        assert cols.get("strategy_id") == "text"
        assert cols.get("report") == "jsonb"
        assert cols.get("computed_at") == "timestamp with time zone"
    finally:
        await conn.close()


async def test_schema_tables_exist(settings: Settings) -> None:
    """All expected tables must exist in both databases (including Phase 2)."""
    import asyncpg

    conn = await asyncpg.connect(settings.csm_set_dsn)
    try:
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        tables = {r["table_name"] for r in rows}
        assert "equity_curve" in tables
        assert "trade_history" in tables
        assert "backtest_log" in tables
        assert "benchmark_equity_curve" in tables
    finally:
        await conn.close()

    conn = await asyncpg.connect(settings.gateway_dsn)
    try:
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        tables = {r["table_name"] for r in rows}
        assert "daily_performance" in tables
        assert "portfolio_snapshot" in tables
        assert "strategy_report_snapshot" in tables
    finally:
        await conn.close()


async def test_column_names_csm_set(settings: Settings) -> None:
    """equity_curve must use 'equity' not 'nav'; types must match expected."""
    import asyncpg

    conn = await asyncpg.connect(settings.csm_set_dsn)
    try:
        rows = await conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'equity_curve' AND table_schema = 'public'"
        )
        cols = {(r["column_name"], r["data_type"]) for r in rows}
        assert ("time", "timestamp with time zone") in cols
        assert ("strategy_id", "text") in cols
        assert ("equity", "double precision") in cols
    finally:
        await conn.close()


async def test_column_names_gateway(settings: Settings) -> None:
    """daily_performance must have daily_return and cumulative_return, not daily_pnl."""
    import asyncpg

    conn = await asyncpg.connect(settings.gateway_dsn)
    try:
        rows = await conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'daily_performance' AND table_schema = 'public'"
        )
        cols = {(r["column_name"], r["data_type"]) for r in rows}
        assert ("daily_return", "double precision") in cols
        assert ("cumulative_return", "double precision") in cols
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# market_data store (feature-market-data-engine, Phase 1). DSN = db_market_data.
# Mutation tests run inside a transaction that is rolled back, so the live DB is
# left pristine.
# ---------------------------------------------------------------------------


async def test_market_data_reachable_and_timescaledb(settings: Settings) -> None:
    """db_market_data is reachable and has the TimescaleDB extension."""
    import asyncpg

    conn = await asyncpg.connect(settings.market_data_dsn)
    try:
        assert await conn.fetchval("SELECT 1") == 1
        row = await conn.fetchrow("SELECT extname FROM pg_extension WHERE extname = 'timescaledb'")
        assert row is not None and row["extname"] == "timescaledb"
    finally:
        await conn.close()


async def test_market_data_ohlcv_is_hypertable(settings: Settings) -> None:
    """market_data.ohlcv must be a registered hypertable."""
    import asyncpg

    conn = await asyncpg.connect(settings.market_data_dsn)
    try:
        rows = await conn.fetch(
            "SELECT hypertable_schema, hypertable_name FROM timescaledb_information.hypertables"
        )
        hypertables = {(r["hypertable_schema"], r["hypertable_name"]) for r in rows}
        assert ("market_data", "ohlcv") in hypertables
    finally:
        await conn.close()


async def test_market_data_schema_columns_and_types(settings: Settings) -> None:
    """ohlcv columns/types match the Phase 1 schema (numeric(18,6) prices)."""
    import asyncpg

    conn = await asyncpg.connect(settings.market_data_dsn)
    try:
        rows = await conn.fetch(
            "SELECT column_name, data_type, numeric_precision, numeric_scale "
            "FROM information_schema.columns "
            "WHERE table_schema = 'market_data' AND table_name = 'ohlcv'"
        )
        cols = {r["column_name"]: r for r in rows}
        assert cols["ts"]["data_type"] == "timestamp with time zone"
        for price in ("open", "high", "low", "close"):
            assert cols[price]["data_type"] == "numeric"
            assert cols[price]["numeric_precision"] == 18
            assert cols[price]["numeric_scale"] == 6
        assert cols["volume"]["numeric_precision"] == 20
        assert cols["volume"]["numeric_scale"] == 4
        assert cols["open_interest"]["numeric_scale"] == 4

        # timeframe CHECK constraint exists and lists the three timeframes.
        constraints = await conn.fetch(
            "SELECT pg_get_constraintdef(c.oid) AS def FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE n.nspname = 'market_data' AND t.relname = 'ohlcv' "
            "AND c.contype = 'c'"
        )
        defs = " ".join(r["def"] for r in constraints)
        for token in ("'1d'", "'1h'", "'5m'"):
            assert token in defs
    finally:
        await conn.close()


async def test_market_data_companion_tables_and_view(settings: Settings) -> None:
    """corporate_actions, universe_membership tables and the adjusted view exist."""
    import asyncpg

    conn = await asyncpg.connect(settings.market_data_dsn)
    try:
        tables = {
            r["table_name"]
            for r in await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'market_data'"
            )
        }
        assert {"ohlcv", "corporate_actions", "universe_membership"} <= tables
        view = await conn.fetchval(
            "SELECT table_name FROM information_schema.views "
            "WHERE table_schema = 'market_data' AND table_name = 'ohlcv_adjusted'"
        )
        assert view == "ohlcv_adjusted"
    finally:
        await conn.close()


async def test_market_data_caggs_registered(settings: Settings) -> None:
    """Derived-TF continuous aggregates must be registered."""
    import asyncpg

    conn = await asyncpg.connect(settings.market_data_dsn)
    try:
        views = {
            r["view_name"]
            for r in await conn.fetch(
                "SELECT view_name FROM timescaledb_information.continuous_aggregates"
            )
        }
        assert "cagg_ohlcv_1h" in views
        assert "cagg_ohlcv_4h" in views
    finally:
        await conn.close()


async def test_market_data_upsert_idempotent(settings: Settings) -> None:
    """Re-upserting the same (symbol, timeframe, ts) updates in place — no dup rows."""
    import asyncpg

    conn = await asyncpg.connect(settings.market_data_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        sym = "TEST:IDEMPOTENT"
        sql = (
            "INSERT INTO market_data.ohlcv "
            "(symbol, timeframe, ts, open, high, low, close, volume) "
            "VALUES ($1,'1d','2026-05-29 00:00+00',$2,$2,$2,$2,$3) "
            "ON CONFLICT (symbol, timeframe, ts) DO UPDATE SET close = EXCLUDED.close"
        )
        await conn.execute(sql, sym, 100, 1000)
        await conn.execute(sql, sym, 200, 1000)  # same key, different price
        count = await conn.fetchval("SELECT count(*) FROM market_data.ohlcv WHERE symbol = $1", sym)
        close = await conn.fetchval("SELECT close FROM market_data.ohlcv WHERE symbol = $1", sym)
        assert count == 1
        assert close == 200
    finally:
        await tr.rollback()
        await conn.close()


async def test_market_data_constraints_reject_bad_rows(settings: Settings) -> None:
    """CHECK constraints reject bad timeframe / non-positive price / negative volume / high<low."""
    import asyncpg

    conn = await asyncpg.connect(settings.market_data_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        base = (
            "INSERT INTO market_data.ohlcv "
            "(symbol, timeframe, ts, open, high, low, close, volume) VALUES "
        )
        bad_rows = [
            f"{base}('X','15m','2026-01-01 00:00+00',1,1,1,1,0)",  # bad timeframe
            f"{base}('X','5m','2026-01-01 00:00+00',-1,1,1,1,0)",  # non-positive price
            f"{base}('X','5m','2026-01-01 00:00+00',1,1,1,1,-5)",  # negative volume
            f"{base}('X','5m','2026-01-01 00:00+00',1,1,9,1,0)",  # high < low
        ]
        for stmt in bad_rows:
            with pytest.raises(asyncpg.exceptions.CheckViolationError):
                async with conn.transaction():
                    await conn.execute(stmt)
    finally:
        await tr.rollback()
        await conn.close()


async def test_market_data_adjusted_view_recomputes_on_action(settings: Settings) -> None:
    """The adjusted view back-adjusts prior bars the moment a corporate_actions row lands."""
    import asyncpg

    conn = await asyncpg.connect(settings.market_data_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        sym = "TEST:ADJ"
        await conn.execute(
            "INSERT INTO market_data.ohlcv "
            "(symbol, timeframe, ts, open, high, low, close, volume) VALUES "
            f"('{sym}','1d','2026-05-28 00:00+00',100,101,99,100,1000),"
            f"('{sym}','1d','2026-05-29 00:00+00',100,102,98,100,2000)"
        )
        adj_before = await conn.fetchval(
            "SELECT close FROM market_data.ohlcv_adjusted "
            "WHERE symbol = $1 AND ts = '2026-05-28 00:00+00'",
            sym,
        )
        assert adj_before == 100  # no action yet → unadjusted

        await conn.execute(
            "INSERT INTO market_data.corporate_actions "
            "(symbol, ex_date, action_type, ratio, amount) "
            f"VALUES ('{sym}','2026-05-29','split',0.5,2)"
        )
        adj_after = await conn.fetchval(
            "SELECT close FROM market_data.ohlcv_adjusted "
            "WHERE symbol = $1 AND ts = '2026-05-28 00:00+00'",
            sym,
        )
        adj_exdate = await conn.fetchval(
            "SELECT close FROM market_data.ohlcv_adjusted "
            "WHERE symbol = $1 AND ts = '2026-05-29 00:00+00'",
            sym,
        )
        assert adj_after == 50  # prior bar back-adjusted by ratio 0.5
        assert adj_exdate == 100  # bar on/after ex_date unchanged
    finally:
        await tr.rollback()
        await conn.close()


async def test_market_data_read_query_is_index_backed(settings: Settings) -> None:
    """The documented read query uses the (symbol, timeframe, ts DESC) index, not a seq scan."""
    import asyncpg

    conn = await asyncpg.connect(settings.market_data_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        await conn.execute(
            "INSERT INTO market_data.ohlcv "
            "(symbol, timeframe, ts, open, high, low, close, volume) "
            "VALUES ('TEST:IDX','1d','2026-05-29 00:00+00',1,1,1,1,0)"
        )
        plan = "\n".join(
            r["QUERY PLAN"]
            for r in await conn.fetch(
                "EXPLAIN SELECT * FROM market_data.ohlcv "
                "WHERE symbol = 'TEST:IDX' AND timeframe = '1d' ORDER BY ts DESC LIMIT 10"
            )
        )
        assert "Index Scan" in plan
        assert "Seq Scan" not in plan
    finally:
        await tr.rollback()
        await conn.close()
