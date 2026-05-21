"""Unit tests for src/db/repositories.py with mocked asyncpg pools."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.db.errors import RepositoryError
from src.db.models import (
    BenchmarkEquityCurveRow,
    StrategyReportSnapshotRow,
    TradeHistoryRow,
)
from src.db.repositories import (
    fetch_benchmark_curve,
    fetch_strategy_report,
    fetch_trade_history,
    upsert_benchmark_equity,
    upsert_strategy_report,
    upsert_trade_history,
)


def _mock_pool_with_conn(conn: MagicMock) -> MagicMock:
    """Build a MagicMock pool whose `acquire()` async-context-yields `conn`."""
    pool = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    pool.acquire.return_value.__aexit__.return_value = None
    return pool


def _make_trade_row(**overrides: object) -> TradeHistoryRow:
    base: dict[str, object] = {
        "time": datetime(2026, 1, 2, tzinfo=UTC),
        "strategy_id": "csm-set-01",
        "symbol": "SET:PTT",
        "side": "LONG",
        "quantity": 100.0,
        "price": 42.5,
    }
    base.update(overrides)
    return TradeHistoryRow(**base)  # type: ignore[arg-type]


class TestUpsertTradeHistory:
    async def test_empty_input_short_circuits(self) -> None:
        pool = MagicMock()
        result = await upsert_trade_history(pool, [])
        assert result == 0
        pool.acquire.assert_not_called()

    async def test_executes_executemany_with_full_payload(self) -> None:
        conn = MagicMock()
        conn.executemany = AsyncMock()
        pool = _mock_pool_with_conn(conn)
        rows = [
            _make_trade_row(),
            _make_trade_row(side="SHORT", realized_pnl=Decimal("12.50")),
        ]
        count = await upsert_trade_history(pool, rows)
        assert count == 2
        conn.executemany.assert_awaited_once()
        sql_arg = conn.executemany.await_args.args[0]
        payload_arg = conn.executemany.await_args.args[1]
        assert "INSERT INTO trade_history" in sql_arg
        assert "ON CONFLICT (strategy_id, time, symbol, side)" in sql_arg
        assert len(payload_arg) == 2
        # 11 positional params per row to match the 11-column INSERT
        assert all(len(tup) == 11 for tup in payload_arg)

    async def test_wraps_asyncpg_error(self) -> None:
        conn = MagicMock()
        conn.executemany = AsyncMock(side_effect=OSError("boom"))
        pool = _mock_pool_with_conn(conn)
        with pytest.raises(RepositoryError, match="upsert_trade_history failed"):
            await upsert_trade_history(pool, [_make_trade_row()])


class TestFetchTradeHistory:
    async def test_without_since_uses_two_param_query(self) -> None:
        record = {
            "time": datetime(2026, 1, 2, tzinfo=UTC),
            "strategy_id": "csm-set-01",
            "symbol": "SET:PTT",
            "side": "LONG",
            "quantity": 100.0,
            "price": 42.5,
            "commission": 0.0,
            "entry_price": None,
            "exit_price": None,
            "realized_pnl": None,
            "duration_bars": None,
        }
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[record])
        pool = _mock_pool_with_conn(conn)
        rows = await fetch_trade_history(pool, strategy_id="csm-set-01")
        assert len(rows) == 1
        assert isinstance(rows[0], TradeHistoryRow)
        args = conn.fetch.await_args.args
        assert args[1] == "csm-set-01"
        assert args[2] == 1000  # default limit

    async def test_with_since_uses_three_param_query(self) -> None:
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        pool = _mock_pool_with_conn(conn)
        since = datetime(2026, 1, 1, tzinfo=UTC)
        rows = await fetch_trade_history(pool, strategy_id="csm-set-01", since=since, limit=50)
        assert rows == []
        args = conn.fetch.await_args.args
        assert "AND time >= $2" in args[0]
        assert args[1] == "csm-set-01"
        assert args[2] == since
        assert args[3] == 50

    async def test_wraps_asyncpg_error(self) -> None:
        conn = MagicMock()
        conn.fetch = AsyncMock(side_effect=OSError("boom"))
        pool = _mock_pool_with_conn(conn)
        with pytest.raises(RepositoryError, match="fetch_trade_history failed"):
            await fetch_trade_history(pool, strategy_id="csm-set-01")


class TestUpsertBenchmarkEquity:
    async def test_empty_input_short_circuits(self) -> None:
        pool = MagicMock()
        result = await upsert_benchmark_equity(pool, [])
        assert result == 0

    async def test_executes_executemany(self) -> None:
        conn = MagicMock()
        conn.executemany = AsyncMock()
        pool = _mock_pool_with_conn(conn)
        rows = [
            BenchmarkEquityCurveRow(
                time=datetime(2026, 1, 2, tzinfo=UTC),
                strategy_id="csm-set-01",
                benchmark_symbol="SET:SET",
                equity=Decimal("1000.0"),
            ),
        ]
        count = await upsert_benchmark_equity(pool, rows)
        assert count == 1
        sql_arg = conn.executemany.await_args.args[0]
        assert "INSERT INTO benchmark_equity_curve" in sql_arg
        assert "ON CONFLICT (time, strategy_id, benchmark_symbol)" in sql_arg

    async def test_wraps_asyncpg_error(self) -> None:
        conn = MagicMock()
        conn.executemany = AsyncMock(side_effect=OSError("boom"))
        pool = _mock_pool_with_conn(conn)
        rows = [
            BenchmarkEquityCurveRow(
                time=datetime(2026, 1, 2, tzinfo=UTC),
                strategy_id="csm-set-01",
                benchmark_symbol="SET:SET",
                equity=Decimal("1.0"),
            ),
        ]
        with pytest.raises(RepositoryError, match="upsert_benchmark_equity failed"):
            await upsert_benchmark_equity(pool, rows)


class TestFetchBenchmarkCurve:
    async def test_without_since(self) -> None:
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        pool = _mock_pool_with_conn(conn)
        result = await fetch_benchmark_curve(
            pool, strategy_id="csm-set-01", benchmark_symbol="SET:SET"
        )
        assert result == []
        args = conn.fetch.await_args.args
        assert "ORDER BY time ASC" in args[0]
        assert args[1] == "csm-set-01"
        assert args[2] == "SET:SET"

    async def test_with_since(self) -> None:
        since = datetime(2026, 1, 1, tzinfo=UTC)
        record = {
            "time": datetime(2026, 1, 2, tzinfo=UTC),
            "strategy_id": "csm-set-01",
            "benchmark_symbol": "SET:SET",
            "equity": Decimal("1000.0"),
        }
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[record])
        pool = _mock_pool_with_conn(conn)
        result = await fetch_benchmark_curve(
            pool, strategy_id="csm-set-01", benchmark_symbol="SET:SET", since=since
        )
        assert len(result) == 1
        assert result[0].equity == Decimal("1000.0")
        assert "AND time >= $3" in conn.fetch.await_args.args[0]

    async def test_wraps_asyncpg_error(self) -> None:
        conn = MagicMock()
        conn.fetch = AsyncMock(side_effect=OSError("boom"))
        pool = _mock_pool_with_conn(conn)
        with pytest.raises(RepositoryError, match="fetch_benchmark_curve failed"):
            await fetch_benchmark_curve(pool, strategy_id="csm-set-01", benchmark_symbol="SET:SET")


class TestUpsertStrategyReport:
    async def test_executes_with_serialized_json(self) -> None:
        conn = MagicMock()
        conn.execute = AsyncMock()
        pool = _mock_pool_with_conn(conn)
        row = StrategyReportSnapshotRow(
            time=datetime(2026, 1, 2, tzinfo=UTC),
            strategy_id="csm-set-01",
            report={"headline": {"total_pnl": "123.45"}},
        )
        await upsert_strategy_report(pool, row)
        args = conn.execute.await_args.args
        assert "INSERT INTO strategy_report_snapshot" in args[0]
        assert "ON CONFLICT (time, strategy_id)" in args[0]
        assert args[1] == row.time
        assert args[2] == "csm-set-01"
        assert json.loads(args[3]) == {"headline": {"total_pnl": "123.45"}}

    async def test_wraps_asyncpg_error(self) -> None:
        conn = MagicMock()
        conn.execute = AsyncMock(side_effect=OSError("boom"))
        pool = _mock_pool_with_conn(conn)
        row = StrategyReportSnapshotRow(
            time=datetime(2026, 1, 2, tzinfo=UTC),
            strategy_id="csm-set-01",
            report={},
        )
        with pytest.raises(RepositoryError, match="upsert_strategy_report failed"):
            await upsert_strategy_report(pool, row)


class TestFetchStrategyReport:
    async def test_returns_row_when_found_with_dict_report(self) -> None:
        record = {
            "time": datetime(2026, 1, 2, tzinfo=UTC),
            "strategy_id": "csm-set-01",
            "report": {"headline": {"total_pnl": "123.45"}},
            "computed_at": datetime(2026, 1, 2, tzinfo=UTC),
        }
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=record)
        pool = _mock_pool_with_conn(conn)
        result = await fetch_strategy_report(
            pool, strategy_id="csm-set-01", at_time=datetime(2026, 1, 2, tzinfo=UTC)
        )
        assert result is not None
        assert result.report["headline"]["total_pnl"] == "123.45"

    async def test_decodes_report_when_returned_as_json_string(self) -> None:
        record = {
            "time": datetime(2026, 1, 2, tzinfo=UTC),
            "strategy_id": "csm-set-01",
            "report": '{"headline": {"total_pnl": "123.45"}}',
            "computed_at": datetime(2026, 1, 2, tzinfo=UTC),
        }
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=record)
        pool = _mock_pool_with_conn(conn)
        result = await fetch_strategy_report(
            pool, strategy_id="csm-set-01", at_time=datetime(2026, 1, 2, tzinfo=UTC)
        )
        assert result is not None
        assert result.report == {"headline": {"total_pnl": "123.45"}}

    async def test_returns_none_when_not_found(self) -> None:
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=None)
        pool = _mock_pool_with_conn(conn)
        result = await fetch_strategy_report(
            pool, strategy_id="csm-set-01", at_time=datetime(2026, 1, 2, tzinfo=UTC)
        )
        assert result is None

    async def test_wraps_asyncpg_error(self) -> None:
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=OSError("boom"))
        pool = _mock_pool_with_conn(conn)
        with pytest.raises(RepositoryError, match="fetch_strategy_report failed"):
            await fetch_strategy_report(
                pool, strategy_id="csm-set-01", at_time=datetime(2026, 1, 2, tzinfo=UTC)
            )
