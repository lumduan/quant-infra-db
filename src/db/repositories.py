"""Async asyncpg repository helpers for the Strategies-Report-Metrics tables.

Each function takes an `asyncpg.Pool` (created via `create_postgres_pool`) and
uses parameterized SQL with `INSERT … ON CONFLICT (…) DO UPDATE SET …` against
the UNIQUE indexes declared in `init-scripts/03_…` and `05_…`.

Errors from `asyncpg` are wrapped in `RepositoryError` so callers can catch a
single, project-local exception type.
"""

import json
import logging
from collections.abc import Sequence
from datetime import datetime

import asyncpg

from src.db.errors import RepositoryError
from src.db.models import (
    BenchmarkEquityCurveRow,
    StrategyReportSnapshotRow,
    TradeHistoryRow,
)

logger = logging.getLogger(__name__)


_TRADE_HISTORY_UPSERT_SQL = """
INSERT INTO trade_history (
    time, strategy_id, symbol, side, quantity, price, commission,
    entry_price, exit_price, realized_pnl, duration_bars
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
ON CONFLICT (strategy_id, time, symbol, side) DO UPDATE SET
    quantity      = EXCLUDED.quantity,
    price         = EXCLUDED.price,
    commission    = EXCLUDED.commission,
    entry_price   = EXCLUDED.entry_price,
    exit_price    = EXCLUDED.exit_price,
    realized_pnl  = EXCLUDED.realized_pnl,
    duration_bars = EXCLUDED.duration_bars
"""

_BENCHMARK_UPSERT_SQL = """
INSERT INTO benchmark_equity_curve (time, strategy_id, benchmark_symbol, equity)
VALUES ($1, $2, $3, $4)
ON CONFLICT (time, strategy_id, benchmark_symbol) DO UPDATE SET
    equity = EXCLUDED.equity
"""

_STRATEGY_REPORT_UPSERT_SQL = """
INSERT INTO strategy_report_snapshot (time, strategy_id, report, computed_at)
VALUES ($1, $2, $3::jsonb, $4)
ON CONFLICT (time, strategy_id) DO UPDATE SET
    report      = EXCLUDED.report,
    computed_at = EXCLUDED.computed_at
"""


async def upsert_trade_history(pool: asyncpg.Pool, rows: Sequence[TradeHistoryRow]) -> int:
    """Upsert a batch of trade_history rows. Returns the row count written."""
    if not rows:
        return 0
    payload = [
        (
            r.time,
            r.strategy_id,
            r.symbol,
            r.side,
            r.quantity,
            r.price,
            r.commission,
            r.entry_price,
            r.exit_price,
            r.realized_pnl,
            r.duration_bars,
        )
        for r in rows
    ]
    try:
        async with pool.acquire() as conn:
            await conn.executemany(_TRADE_HISTORY_UPSERT_SQL, payload)
    except Exception as exc:
        raise RepositoryError(f"upsert_trade_history failed: {exc}") from exc
    logger.info("upserted %d trade_history rows", len(payload))
    return len(payload)


async def fetch_trade_history(
    pool: asyncpg.Pool,
    *,
    strategy_id: str,
    since: datetime | None = None,
    limit: int = 1000,
) -> list[TradeHistoryRow]:
    """Fetch recent trades for a strategy, newest first."""
    try:
        async with pool.acquire() as conn:
            if since is None:
                records = await conn.fetch(
                    "SELECT time, strategy_id, symbol, side, quantity, price, commission, "
                    "entry_price, exit_price, realized_pnl, duration_bars "
                    "FROM trade_history WHERE strategy_id = $1 "
                    "ORDER BY time DESC LIMIT $2",
                    strategy_id,
                    limit,
                )
            else:
                records = await conn.fetch(
                    "SELECT time, strategy_id, symbol, side, quantity, price, commission, "
                    "entry_price, exit_price, realized_pnl, duration_bars "
                    "FROM trade_history WHERE strategy_id = $1 AND time >= $2 "
                    "ORDER BY time DESC LIMIT $3",
                    strategy_id,
                    since,
                    limit,
                )
    except Exception as exc:
        raise RepositoryError(f"fetch_trade_history failed: {exc}") from exc
    return [TradeHistoryRow(**dict(r)) for r in records]


async def upsert_benchmark_equity(
    pool: asyncpg.Pool, rows: Sequence[BenchmarkEquityCurveRow]
) -> int:
    """Upsert a batch of benchmark_equity_curve rows. Returns the row count written."""
    if not rows:
        return 0
    payload = [(r.time, r.strategy_id, r.benchmark_symbol, r.equity) for r in rows]
    try:
        async with pool.acquire() as conn:
            await conn.executemany(_BENCHMARK_UPSERT_SQL, payload)
    except Exception as exc:
        raise RepositoryError(f"upsert_benchmark_equity failed: {exc}") from exc
    logger.info("upserted %d benchmark_equity_curve rows", len(payload))
    return len(payload)


async def fetch_benchmark_curve(
    pool: asyncpg.Pool,
    *,
    strategy_id: str,
    benchmark_symbol: str,
    since: datetime | None = None,
) -> list[BenchmarkEquityCurveRow]:
    """Fetch the benchmark curve for (strategy, symbol), oldest first."""
    try:
        async with pool.acquire() as conn:
            if since is None:
                records = await conn.fetch(
                    "SELECT time, strategy_id, benchmark_symbol, equity "
                    "FROM benchmark_equity_curve "
                    "WHERE strategy_id = $1 AND benchmark_symbol = $2 "
                    "ORDER BY time ASC",
                    strategy_id,
                    benchmark_symbol,
                )
            else:
                records = await conn.fetch(
                    "SELECT time, strategy_id, benchmark_symbol, equity "
                    "FROM benchmark_equity_curve "
                    "WHERE strategy_id = $1 AND benchmark_symbol = $2 AND time >= $3 "
                    "ORDER BY time ASC",
                    strategy_id,
                    benchmark_symbol,
                    since,
                )
    except Exception as exc:
        raise RepositoryError(f"fetch_benchmark_curve failed: {exc}") from exc
    return [BenchmarkEquityCurveRow(**dict(r)) for r in records]


async def upsert_strategy_report(pool: asyncpg.Pool, row: StrategyReportSnapshotRow) -> None:
    """Upsert a single strategy_report_snapshot row."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                _STRATEGY_REPORT_UPSERT_SQL,
                row.time,
                row.strategy_id,
                json.dumps(row.report),
                row.computed_at,
            )
    except Exception as exc:
        raise RepositoryError(f"upsert_strategy_report failed: {exc}") from exc
    logger.info("upserted strategy_report_snapshot for %s @ %s", row.strategy_id, row.time)


async def fetch_strategy_report(
    pool: asyncpg.Pool, *, strategy_id: str, at_time: datetime
) -> StrategyReportSnapshotRow | None:
    """Fetch the report snapshot for (strategy, time), or None if missing."""
    try:
        async with pool.acquire() as conn:
            record = await conn.fetchrow(
                "SELECT time, strategy_id, report, computed_at "
                "FROM strategy_report_snapshot "
                "WHERE strategy_id = $1 AND time = $2",
                strategy_id,
                at_time,
            )
    except Exception as exc:
        raise RepositoryError(f"fetch_strategy_report failed: {exc}") from exc
    if record is None:
        return None
    payload = dict(record)
    if isinstance(payload["report"], str):
        payload["report"] = json.loads(payload["report"])
    return StrategyReportSnapshotRow(**payload)
