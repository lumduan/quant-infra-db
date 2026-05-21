"""Unit tests for Pydantic V2 row models (no DB access)."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError
from src.db.models import (
    BenchmarkEquityCurveRow,
    StrategyReportSnapshotRow,
    TradeHistoryRow,
)


class TestTradeHistoryRow:
    def test_minimal_valid_row(self) -> None:
        row = TradeHistoryRow(
            time=datetime(2026, 1, 2, tzinfo=UTC),
            strategy_id="csm-set-01",
            symbol="SET:PTT",
            side="LONG",
            quantity=100.0,
            price=42.5,
        )
        assert row.commission == 0.0
        assert row.entry_price is None
        assert row.realized_pnl is None
        assert row.duration_bars is None

    def test_full_phase2_columns(self) -> None:
        row = TradeHistoryRow(
            time=datetime(2026, 1, 2, tzinfo=UTC),
            strategy_id="csm-set-01",
            symbol="SET:PTT",
            side="SHORT",
            quantity=100.0,
            price=42.5,
            commission=0.25,
            entry_price=Decimal("42.5"),
            exit_price=Decimal("41.0"),
            realized_pnl=Decimal("150.00"),
            duration_bars=5,
        )
        assert row.realized_pnl == Decimal("150.00")
        assert row.duration_bars == 5

    def test_side_rejects_unknown_value(self) -> None:
        with pytest.raises(ValidationError, match="side must be one of"):
            TradeHistoryRow(
                time=datetime(2026, 1, 2, tzinfo=UTC),
                strategy_id="csm-set-01",
                symbol="SET:PTT",
                side="FLAT",
                quantity=1.0,
                price=1.0,
            )

    def test_naive_datetime_coerced_to_utc(self) -> None:
        row = TradeHistoryRow(
            time=datetime(2026, 1, 2, 9, 30),
            strategy_id="csm-set-01",
            symbol="SET:PTT",
            side="LONG",
            quantity=1.0,
            price=1.0,
        )
        assert row.time.tzinfo is UTC

    def test_non_utc_tz_rejected(self) -> None:
        bangkok = timezone(timedelta(hours=7))
        with pytest.raises(ValidationError, match="datetime must be UTC"):
            TradeHistoryRow(
                time=datetime(2026, 1, 2, 16, 30, tzinfo=bangkok),
                strategy_id="csm-set-01",
                symbol="SET:PTT",
                side="LONG",
                quantity=1.0,
                price=1.0,
            )

    def test_negative_duration_bars_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TradeHistoryRow(
                time=datetime(2026, 1, 2, tzinfo=UTC),
                strategy_id="csm-set-01",
                symbol="SET:PTT",
                side="LONG",
                quantity=1.0,
                price=1.0,
                duration_bars=-1,
            )

    def test_frozen_model_rejects_assignment(self) -> None:
        row = TradeHistoryRow(
            time=datetime(2026, 1, 2, tzinfo=UTC),
            strategy_id="csm-set-01",
            symbol="SET:PTT",
            side="LONG",
            quantity=1.0,
            price=1.0,
        )
        with pytest.raises(ValidationError):
            row.side = "SHORT"

    def test_empty_strategy_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TradeHistoryRow(
                time=datetime(2026, 1, 2, tzinfo=UTC),
                strategy_id="",
                symbol="SET:PTT",
                side="LONG",
                quantity=1.0,
                price=1.0,
            )

    def test_all_allowed_sides_accepted(self) -> None:
        for side in ("LONG", "SHORT", "BUY", "SELL", "HOLD"):
            row = TradeHistoryRow(
                time=datetime(2026, 1, 2, tzinfo=UTC),
                strategy_id="csm-set-01",
                symbol="SET:PTT",
                side=side,
                quantity=1.0,
                price=1.0,
            )
            assert row.side == side


class TestBenchmarkEquityCurveRow:
    def test_valid_row(self) -> None:
        row = BenchmarkEquityCurveRow(
            time=datetime(2026, 1, 2, tzinfo=UTC),
            strategy_id="csm-set-01",
            benchmark_symbol="SET:SET",
            equity=Decimal("1000000.0000"),
        )
        assert isinstance(row.equity, Decimal)
        assert row.equity == Decimal("1000000.0000")

    def test_naive_datetime_coerced(self) -> None:
        row = BenchmarkEquityCurveRow(
            time=datetime(2026, 1, 2),
            strategy_id="csm-set-01",
            benchmark_symbol="SET:SET",
            equity=Decimal("1000.0"),
        )
        assert row.time.tzinfo is UTC

    def test_missing_required_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BenchmarkEquityCurveRow(  # type: ignore[call-arg]
                time=datetime(2026, 1, 2, tzinfo=UTC),
                strategy_id="csm-set-01",
                benchmark_symbol="SET:SET",
            )


class TestStrategyReportSnapshotRow:
    def test_valid_row(self) -> None:
        row = StrategyReportSnapshotRow(
            time=datetime(2026, 1, 2, tzinfo=UTC),
            strategy_id="csm-set-01",
            report={"headline": {"total_pnl": "123.45"}},
        )
        assert row.report["headline"]["total_pnl"] == "123.45"
        assert row.computed_at.tzinfo is UTC

    def test_default_computed_at_is_utc(self) -> None:
        before = datetime.now(tz=UTC)
        row = StrategyReportSnapshotRow(
            time=datetime(2026, 1, 2, tzinfo=UTC),
            strategy_id="csm-set-01",
            report={},
        )
        after = datetime.now(tz=UTC)
        assert before <= row.computed_at <= after

    def test_explicit_computed_at_validated(self) -> None:
        row = StrategyReportSnapshotRow(
            time=datetime(2026, 1, 2, tzinfo=UTC),
            strategy_id="csm-set-01",
            report={},
            computed_at=datetime(2026, 1, 2, 10),
        )
        assert row.computed_at.tzinfo is UTC

    def test_non_utc_computed_at_rejected(self) -> None:
        with pytest.raises(ValidationError, match="datetime must be UTC"):
            StrategyReportSnapshotRow(
                time=datetime(2026, 1, 2, tzinfo=UTC),
                strategy_id="csm-set-01",
                report={},
                computed_at=datetime(2026, 1, 2, tzinfo=timezone(timedelta(hours=7))),
            )
