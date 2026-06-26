"""Live-DB tests for the read-only monitor role (19_monitor_role.sql).

The quant-monitor system dashboard (host :8900) reads the capture stores through a
SELECT-only `monitor` role. This verifies the script applies idempotently and that
`monitor` has read-only privileges (SELECT, never INSERT/UPDATE/DELETE) on the
orderbook + ticker schemas.

Run with a live stack: uv run pytest -m infra
"""

import subprocess

import pytest
from src.config import Settings

pytestmark = pytest.mark.infra

# 19 grants on orderbook.* + ticker.*, so its prerequisites must exist first.
_BOOTSTRAP = (
    "01_create_databases.sql",
    "02_enable_timescaledb.sql",
    "14_schema_orderbook.sql",
    "17_schema_ticker.sql",
    "18_ticker_dq.sql",
    "19_monitor_role.sql",
)


@pytest.fixture
def settings() -> Settings:
    """Load settings from the real .env file (requires .env with valid POSTGRES_PASSWORD)."""
    return Settings()


def _apply(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "exec",
            "quant-postgres",
            "psql",
            "-U",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            f"/docker-entrypoint-initdb.d/{script}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_monitor_role_applies_idempotently() -> None:
    """19 (with its prerequisites) applies cleanly against the live container — twice."""
    for _ in range(2):
        for script in _BOOTSTRAP:
            result = _apply(script)
            assert result.returncode == 0, f"{script} failed: {result.stderr}"


async def test_monitor_role_is_read_only_orderbook(settings: Settings) -> None:
    """monitor has USAGE + SELECT on orderbook.*, and NO write privileges."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    try:
        assert await conn.fetchval("SELECT has_schema_privilege('monitor', 'orderbook', 'USAGE')")
        for tbl in ("raw_events", "trades", "dq_manifests"):
            assert await conn.fetchval(
                f"SELECT has_table_privilege('monitor', 'orderbook.{tbl}', 'SELECT')"
            )
            for priv in ("INSERT", "UPDATE", "DELETE"):
                assert not await conn.fetchval(
                    f"SELECT has_table_privilege('monitor', 'orderbook.{tbl}', '{priv}')"
                )
    finally:
        await conn.close()


async def test_monitor_role_is_read_only_ticker(settings: Settings) -> None:
    """monitor has USAGE + SELECT on ticker.*, and NO write privileges."""
    import asyncpg

    ticker_dsn = settings.orderbook_dsn.replace("db_orderbook", "db_ticker")
    conn = await asyncpg.connect(ticker_dsn)
    try:
        assert await conn.fetchval("SELECT has_schema_privilege('monitor', 'ticker', 'USAGE')")
        assert await conn.fetchval(
            "SELECT has_table_privilege('monitor', 'ticker.trades', 'SELECT')"
        )
        for priv in ("INSERT", "UPDATE", "DELETE"):
            assert not await conn.fetchval(
                f"SELECT has_table_privilege('monitor', 'ticker.trades', '{priv}')"
            )
    finally:
        await conn.close()
