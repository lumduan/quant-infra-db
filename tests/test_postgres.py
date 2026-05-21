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
