"""Unit tests for Pydantic V2 row models (no DB access)."""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError
from src.db.models import (
    BenchmarkEquityCurveRow,
    CorporateActionRow,
    OHLCVBarRow,
    StrategyReportSnapshotRow,
    TradeHistoryRow,
    UniverseMembershipRow,
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


def _make_bar(**overrides: object) -> OHLCVBarRow:
    base: dict[str, object] = {
        "symbol": "SET:PTT",
        "timeframe": "1d",
        "ts": datetime(2026, 5, 29, tzinfo=UTC),
        "open": Decimal("100.0"),
        "high": Decimal("102.0"),
        "low": Decimal("98.0"),
        "close": Decimal("101.0"),
        "volume": Decimal("1000"),
    }
    base.update(overrides)
    return OHLCVBarRow(**base)  # type: ignore[arg-type]


class TestOHLCVBarRow:
    def test_minimal_valid_equity_bar(self) -> None:
        row = _make_bar()
        assert row.open_interest is None
        assert row.source == "tvkit"
        assert row.ingested_at is None
        assert isinstance(row.close, Decimal)

    def test_futures_bar_with_open_interest(self) -> None:
        row = _make_bar(symbol="S501!", open_interest=Decimal("412330.0"))
        assert row.open_interest == Decimal("412330.0")

    @pytest.mark.parametrize("tf", ["1d", "1h", "5m"])
    def test_allowed_timeframes(self, tf: str) -> None:
        assert _make_bar(timeframe=tf).timeframe == tf

    def test_bad_timeframe_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timeframe must be one of"):
            _make_bar(timeframe="15m")

    def test_naive_ts_coerced_to_utc(self) -> None:
        row = _make_bar(ts=datetime(2026, 5, 29, 7, 0))
        assert row.ts.tzinfo is UTC

    def test_non_utc_ts_rejected(self) -> None:
        with pytest.raises(ValidationError, match="datetime must be UTC"):
            _make_bar(ts=datetime(2026, 5, 29, tzinfo=timezone(timedelta(hours=7))))

    def test_non_positive_price_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_bar(close=Decimal("0"))

    def test_negative_volume_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_bar(volume=Decimal("-1"))

    def test_negative_open_interest_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_bar(open_interest=Decimal("-1"))

    def test_high_below_low_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be >= low"):
            _make_bar(high=Decimal("90"), low=Decimal("95"))

    def test_empty_symbol_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_bar(symbol="")

    def test_ingested_at_non_utc_rejected(self) -> None:
        with pytest.raises(ValidationError, match="datetime must be UTC"):
            _make_bar(ingested_at=datetime(2026, 5, 29, tzinfo=timezone(timedelta(hours=7))))

    def test_frozen(self) -> None:
        row = _make_bar()
        with pytest.raises(ValidationError):
            row.close = Decimal("1")


class TestCorporateActionRow:
    def test_valid_split(self) -> None:
        row = CorporateActionRow(
            symbol="SET:PTT",
            ex_date=date(2026, 5, 29),
            action_type="split",
            ratio=Decimal("0.5"),
            amount=Decimal("2"),
        )
        assert row.action_type == "split"
        assert row.ratio == Decimal("0.5")

    @pytest.mark.parametrize("action", ["split", "dividend", "roll"])
    def test_allowed_action_types(self, action: str) -> None:
        row = CorporateActionRow(symbol="X", ex_date=date(2026, 1, 1), action_type=action)
        assert row.action_type == action

    def test_bad_action_type_rejected(self) -> None:
        with pytest.raises(ValidationError, match="action_type must be one of"):
            CorporateActionRow(symbol="X", ex_date=date(2026, 1, 1), action_type="merger")

    def test_non_positive_ratio_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CorporateActionRow(
                symbol="X", ex_date=date(2026, 1, 1), action_type="split", ratio=Decimal("0")
            )

    def test_optional_fields_default_none(self) -> None:
        row = CorporateActionRow(symbol="X", ex_date=date(2026, 1, 1), action_type="roll")
        assert row.ratio is None
        assert row.amount is None
        assert row.note is None


class TestUniverseMembershipRow:
    def test_valid_row_default_index(self) -> None:
        row = UniverseMembershipRow(as_of=date(2026, 5, 1), symbol="SET:PTT")
        assert row.index_name == "SET"

    def test_explicit_index(self) -> None:
        row = UniverseMembershipRow(as_of=date(2026, 5, 1), symbol="SET:PTT", index_name="SET50")
        assert row.index_name == "SET50"

    def test_empty_symbol_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UniverseMembershipRow(as_of=date(2026, 5, 1), symbol="")
