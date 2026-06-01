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
    CorporateActionRow,
    OHLCVBarRow,
    StrategyReportSnapshotRow,
    TradeHistoryRow,
    UniverseMembershipRow,
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


# ---------------------------------------------------------------------------
# Shared market_data store (feature-market-data-engine, Phase 1).
# These helpers take a pool connected to db_market_data; tables are
# schema-qualified `market_data.*`. ingested_at is DB-defaulted (NOT in the
# INSERT column list) so re-running an ingest does not churn the audit column.
# ---------------------------------------------------------------------------

_OHLCV_UPSERT_SQL = """
INSERT INTO market_data.ohlcv (
    symbol, timeframe, ts, open, high, low, close, volume, open_interest, source
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT (symbol, timeframe, ts) DO UPDATE SET
    open          = EXCLUDED.open,
    high          = EXCLUDED.high,
    low           = EXCLUDED.low,
    close         = EXCLUDED.close,
    volume        = EXCLUDED.volume,
    open_interest = EXCLUDED.open_interest,
    source        = EXCLUDED.source,
    ingested_at   = now()
"""

_CORPORATE_ACTION_UPSERT_SQL = """
INSERT INTO market_data.corporate_actions (
    symbol, ex_date, action_type, ratio, amount, note
)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (symbol, ex_date, action_type) DO UPDATE SET
    ratio       = EXCLUDED.ratio,
    amount      = EXCLUDED.amount,
    note        = EXCLUDED.note,
    ingested_at = now()
"""

_UNIVERSE_MEMBERSHIP_UPSERT_SQL = """
INSERT INTO market_data.universe_membership (as_of, symbol, index_name)
VALUES ($1, $2, $3)
ON CONFLICT (as_of, symbol, index_name) DO UPDATE SET
    ingested_at = now()
"""


async def upsert_ohlcv(pool: asyncpg.Pool, rows: Sequence[OHLCVBarRow]) -> int:
    """Idempotently upsert a batch of raw OHLCV bars. Returns the row count."""
    if not rows:
        return 0
    payload = [
        (
            r.symbol,
            r.timeframe,
            r.ts,
            r.open,
            r.high,
            r.low,
            r.close,
            r.volume,
            r.open_interest,
            r.source,
        )
        for r in rows
    ]
    try:
        async with pool.acquire() as conn:
            await conn.executemany(_OHLCV_UPSERT_SQL, payload)
    except Exception as exc:
        raise RepositoryError(f"upsert_ohlcv failed: {exc}") from exc
    logger.info("upserted %d market_data.ohlcv rows", len(payload))
    return len(payload)


async def fetch_ohlcv(
    pool: asyncpg.Pool,
    *,
    symbol: str,
    timeframe: str,
    since: datetime | None = None,
    limit: int = 1000,
) -> list[OHLCVBarRow]:
    """Fetch raw bars for (symbol, timeframe), newest first (index-backed)."""
    columns = (
        "symbol, timeframe, ts, open, high, low, close, volume, open_interest, source, ingested_at"
    )
    try:
        async with pool.acquire() as conn:
            if since is None:
                records = await conn.fetch(
                    f"SELECT {columns} FROM market_data.ohlcv "
                    "WHERE symbol = $1 AND timeframe = $2 "
                    "ORDER BY ts DESC LIMIT $3",
                    symbol,
                    timeframe,
                    limit,
                )
            else:
                records = await conn.fetch(
                    f"SELECT {columns} FROM market_data.ohlcv "
                    "WHERE symbol = $1 AND timeframe = $2 AND ts >= $3 "
                    "ORDER BY ts DESC LIMIT $4",
                    symbol,
                    timeframe,
                    since,
                    limit,
                )
    except Exception as exc:
        raise RepositoryError(f"fetch_ohlcv failed: {exc}") from exc
    return [OHLCVBarRow(**dict(r)) for r in records]


async def upsert_corporate_actions(pool: asyncpg.Pool, rows: Sequence[CorporateActionRow]) -> int:
    """Idempotently upsert corporate-action / roll rows. Returns the row count."""
    if not rows:
        return 0
    payload = [(r.symbol, r.ex_date, r.action_type, r.ratio, r.amount, r.note) for r in rows]
    try:
        async with pool.acquire() as conn:
            await conn.executemany(_CORPORATE_ACTION_UPSERT_SQL, payload)
    except Exception as exc:
        raise RepositoryError(f"upsert_corporate_actions failed: {exc}") from exc
    logger.info("upserted %d market_data.corporate_actions rows", len(payload))
    return len(payload)


async def upsert_universe_membership(
    pool: asyncpg.Pool, rows: Sequence[UniverseMembershipRow]
) -> int:
    """Idempotently upsert universe-membership rows. Returns the row count."""
    if not rows:
        return 0
    payload = [(r.as_of, r.symbol, r.index_name) for r in rows]
    try:
        async with pool.acquire() as conn:
            await conn.executemany(_UNIVERSE_MEMBERSHIP_UPSERT_SQL, payload)
    except Exception as exc:
        raise RepositoryError(f"upsert_universe_membership failed: {exc}") from exc
    logger.info("upserted %d market_data.universe_membership rows", len(payload))
    return len(payload)
