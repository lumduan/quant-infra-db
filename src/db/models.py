"""Pydantic V2 row models for the Strategies-Report-Metrics schema (Phase 2).

These models map 1:1 to rows in:
    db_csm_set.trade_history            (the four new columns)
    db_csm_set.benchmark_equity_curve   (new hypertable)
    db_gateway.strategy_report_snapshot (new hypertable)

Monetary fields are typed `Decimal` per the project-wide rule "monetary values
are Decimal at the gateway boundary; never float"; asyncpg returns PostgreSQL
NUMERIC as `Decimal` natively. Timestamps are tz-aware UTC `datetime` — naive
values are coerced to UTC; non-UTC tz-aware values are rejected.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_SIDES: frozenset[str] = frozenset({"LONG", "SHORT", "BUY", "SELL", "HOLD"})


def _ensure_utc(value: datetime) -> datetime:
    """Coerce naive datetimes to UTC; reject non-UTC tz-aware datetimes."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("datetime must be UTC")
    return value


class TradeHistoryRow(BaseModel):
    """One row of `db_csm_set.trade_history` including the Phase 2 P&L columns."""

    model_config = ConfigDict(frozen=True)

    time: datetime = Field(description="Trade timestamp (UTC).")
    strategy_id: str = Field(min_length=1, description="Strategy identifier.")
    symbol: str = Field(min_length=1, description="Instrument symbol (e.g. SET:PTT).")
    side: str = Field(description="Side: LONG, SHORT, BUY, SELL, or HOLD.")
    quantity: float = Field(description="Trade quantity (legacy DOUBLE PRECISION).")
    price: float = Field(description="Trade price (legacy DOUBLE PRECISION).")
    commission: float = Field(default=0.0, description="Commission paid (legacy DOUBLE PRECISION).")
    entry_price: Decimal | None = Field(default=None, description="Open price (Phase 2).")
    exit_price: Decimal | None = Field(default=None, description="Close price (Phase 2).")
    realized_pnl: Decimal | None = Field(default=None, description="Closed-trade P&L (Phase 2).")
    duration_bars: int | None = Field(default=None, ge=0, description="Bars held (Phase 2).")

    @field_validator("time")
    @classmethod
    def _validate_time(cls, value: datetime) -> datetime:
        return _ensure_utc(value)

    @field_validator("side")
    @classmethod
    def _validate_side(cls, value: str) -> str:
        if value not in ALLOWED_SIDES:
            raise ValueError(f"side must be one of {sorted(ALLOWED_SIDES)}, got {value!r}")
        return value


class BenchmarkEquityCurveRow(BaseModel):
    """One row of `db_csm_set.benchmark_equity_curve`."""

    model_config = ConfigDict(frozen=True)

    time: datetime = Field(description="Bar timestamp (UTC).")
    strategy_id: str = Field(min_length=1)
    benchmark_symbol: str = Field(min_length=1, description="Benchmark ticker (e.g. SET:SET).")
    equity: Decimal = Field(description="Buy-and-hold NAV at `time`.")

    @field_validator("time")
    @classmethod
    def _validate_time(cls, value: datetime) -> datetime:
        return _ensure_utc(value)


class StrategyReportSnapshotRow(BaseModel):
    """One row of `db_gateway.strategy_report_snapshot`."""

    model_config = ConfigDict(frozen=True)

    time: datetime = Field(description="Logical 'as-of' time for the report (UTC).")
    strategy_id: str = Field(min_length=1)
    report: dict[str, Any] = Field(description="JSONB strategy report payload.")
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=UTC),
        description="Wall-clock time the gateway wrote this snapshot.",
    )

    @field_validator("time", "computed_at")
    @classmethod
    def _validate_timestamps(cls, value: datetime) -> datetime:
        return _ensure_utc(value)
