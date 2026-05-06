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
    """Expected hypertables must exist."""
    import asyncpg

    conn = await asyncpg.connect(settings.csm_set_dsn)
    try:
        rows = await conn.fetch("SELECT hypertable_name FROM timescaledb_information.hypertables")
        hypertables = {r["hypertable_name"] for r in rows}
        assert "equity_curve" in hypertables
    finally:
        await conn.close()

    conn = await asyncpg.connect(settings.gateway_dsn)
    try:
        rows = await conn.fetch("SELECT hypertable_name FROM timescaledb_information.hypertables")
        hypertables = {r["hypertable_name"] for r in rows}
        assert "daily_performance" in hypertables
        assert "portfolio_snapshot" in hypertables
    finally:
        await conn.close()


async def test_schema_tables_exist(settings: Settings) -> None:
    """All expected tables must exist in both databases."""
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
    finally:
        await conn.close()
