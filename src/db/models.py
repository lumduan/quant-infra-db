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

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ALLOWED_SIDES: frozenset[str] = frozenset({"LONG", "SHORT", "BUY", "SELL", "HOLD"})

# Shared market_data store (feature-market-data-engine, Phase 1).
ALLOWED_TIMEFRAMES: frozenset[str] = frozenset({"1d", "1h", "5m"})
ALLOWED_ACTION_TYPES: frozenset[str] = frozenset({"split", "dividend", "roll"})


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


class OHLCVBarRow(BaseModel):
    """One raw bar in `db_market_data.market_data.ohlcv`.

    Option A multi-timeframe model (`timeframe` in the natural key). Prices are
    `Decimal` (DB `numeric(18,6)`); `volume`/`open_interest` are `Decimal`
    (`numeric(20,4)`). `open_interest` is futures-only (None for equities).
    `ts` is the bar-open time in UTC; for futures `1d` the close is the
    settlement price (never a rollup of intraday).
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1, description="Instrument symbol (e.g. SET:PTT, S501!).")
    timeframe: str = Field(description="Bar timeframe: 1d, 1h, or 5m.")
    ts: datetime = Field(description="Bar-open timestamp (UTC).")
    open: Decimal = Field(gt=0, description="Open price.")
    high: Decimal = Field(gt=0, description="High price.")
    low: Decimal = Field(gt=0, description="Low price.")
    close: Decimal = Field(gt=0, description="Close price (settlement for futures 1d).")
    volume: Decimal = Field(default=Decimal(0), ge=0, description="Bar volume.")
    open_interest: Decimal | None = Field(
        default=None, ge=0, description="Open interest (futures only; None for equities)."
    )
    source: str = Field(default="tvkit", min_length=1, description="Provenance.")
    ingested_at: datetime | None = Field(
        default=None, description="Upsert audit time (UTC); DB-defaulted when None."
    )

    @field_validator("ts")
    @classmethod
    def _validate_ts(cls, value: datetime) -> datetime:
        return _ensure_utc(value)

    @field_validator("ingested_at")
    @classmethod
    def _validate_ingested_at(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _ensure_utc(value)

    @field_validator("timeframe")
    @classmethod
    def _validate_timeframe(cls, value: str) -> str:
        if value not in ALLOWED_TIMEFRAMES:
            raise ValueError(
                f"timeframe must be one of {sorted(ALLOWED_TIMEFRAMES)}, got {value!r}"
            )
        return value

    @model_validator(mode="after")
    def _validate_high_ge_low(self) -> "OHLCVBarRow":
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) must be >= low ({self.low})")
        return self


class CorporateActionRow(BaseModel):
    """One row of `market_data.corporate_actions`.

    Splits / dividends (equities) and futures roll dates. `ratio` is the
    multiplicative price back-adjustment factor applied to bars dated strictly
    before `ex_date` (engine-computed); `amount` is the raw event magnitude
    (cash dividend, split label, roll gap) for audit.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1)
    ex_date: date = Field(description="Ex-date (the action applies from this date).")
    action_type: str = Field(description="One of split, dividend, roll.")
    ratio: Decimal | None = Field(
        default=None, gt=0, description="Price back-adjustment multiplier for prior bars."
    )
    amount: Decimal | None = Field(default=None, description="Raw event magnitude (audit).")
    note: str | None = Field(default=None)

    @field_validator("action_type")
    @classmethod
    def _validate_action_type(cls, value: str) -> str:
        if value not in ALLOWED_ACTION_TYPES:
            raise ValueError(
                f"action_type must be one of {sorted(ALLOWED_ACTION_TYPES)}, got {value!r}"
            )
        return value


class UniverseMembershipRow(BaseModel):
    """One row of `market_data.universe_membership` — as-of dated, point-in-time."""

    model_config = ConfigDict(frozen=True)

    as_of: date = Field(description="As-of date of the constituent snapshot.")
    symbol: str = Field(min_length=1)
    index_name: str = Field(default="SET", min_length=1, description="Index (e.g. SET, SET50).")
