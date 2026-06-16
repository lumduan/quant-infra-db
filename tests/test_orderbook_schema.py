"""Live-DB tests for the order-book capture store (14_schema_orderbook.sql +
15_orderbook_greeks.sql).

Phase 1 of feature-orderbook-engine: the durable hot-tier mirror for the
Order-Book Capture engine. Covers idempotent re-apply, the orderbook schema +
its tables, hypertable membership for the three event streams, plain-table
status for the reference tables, numeric/timestamp precision, the read indexes,
idempotent settlement / manifest upserts, and the least-privilege grants.
Also covers ``orderbook.greeks`` (15_orderbook_greeks.sql): columns, PK,
nullable IV/greeks, index, and quant grants.

Run with a live stack: uv run pytest -m infra
"""

import json
import subprocess
from datetime import date
from decimal import Decimal

import pytest
from src.config import Settings

pytestmark = pytest.mark.infra

HYPERTABLES = ("raw_events", "trades", "book_snapshots")
PLAIN_TABLES = ("settlements", "gap_windows", "dq_manifests")
ALL_TABLES = HYPERTABLES + PLAIN_TABLES

INSERT_RAW_EVENT = (
    "INSERT INTO orderbook.raw_events "
    "(ts, source, market, symbol, ns, vs_seq, payload, t_ingest_ns, t_mono_ns, t_event_ns) "
    "VALUES (now(), 'liberator', 'TFEX', $1, 'BidOfferV2', $2, $3::jsonb, $4, $5, NULL)"
)
INSERT_SETTLEMENT = (
    "INSERT INTO orderbook.settlements (date, symbol, settlement_price, source) "
    "VALUES ($1, $2, $3, 'liberator') "
    "ON CONFLICT (date, symbol) DO UPDATE SET settlement_price = EXCLUDED.settlement_price"
)


@pytest.fixture
def settings() -> Settings:
    """Load settings from the real .env file (requires .env with valid POSTGRES_PASSWORD)."""
    return Settings()


def test_schema_reapply_idempotent() -> None:
    """01 + 02 + 14 + 15 apply cleanly against the live container — twice (second run is a no-op).

    Runs first in this module: it also bootstraps db_orderbook on a stack whose
    volume predates the script (init-scripts only auto-run on a fresh volume).
    ON_ERROR_STOP=1 is mandatory — without it psql exits 0 even on errors.
    """
    for _ in range(2):
        for script in (
            "01_create_databases.sql",
            "02_enable_timescaledb.sql",
            "14_schema_orderbook.sql",
            "15_orderbook_greeks.sql",
        ):
            result = subprocess.run(
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
            )
            assert result.returncode == 0, f"{script} failed:\n{result.stderr}"


async def test_orderbook_db_reachable(settings: Settings) -> None:
    """db_orderbook is reachable and carries the orderbook schema + timescaledb."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    try:
        assert await conn.fetchval("SELECT 1") == 1
        schema = await conn.fetchval(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'orderbook'"
        )
        assert schema == "orderbook"
        # Unlike db_execution, the capture store DOES use timescaledb.
        assert await conn.fetchval("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'") == 1
    finally:
        await conn.close()


async def test_orderbook_tables_exist(settings: Settings) -> None:
    """All seven orderbook tables exist (including greeks)."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    try:
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'orderbook'"
        )
        tables = {r["table_name"] for r in rows}
        assert set(ALL_TABLES) <= tables
        assert "greeks" in tables
    finally:
        await conn.close()


async def test_event_streams_are_hypertables(settings: Settings) -> None:
    """raw_events / trades / book_snapshots are TimescaleDB hypertables; the rest are plain."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    try:
        rows = await conn.fetch(
            "SELECT hypertable_name FROM timescaledb_information.hypertables "
            "WHERE hypertable_schema = 'orderbook'"
        )
        hypertables = {r["hypertable_name"] for r in rows}
        assert set(HYPERTABLES) <= hypertables
        for plain in PLAIN_TABLES:
            assert plain not in hypertables
        # greeks is a low-cardinality derived table — plain, not a hypertable.
        assert "greeks" not in hypertables
    finally:
        await conn.close()


async def test_raw_events_columns(settings: Settings) -> None:
    """raw_events carries the ns timestamps as bigint + payload jsonb + nullable vs_seq."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    try:
        rows = await conn.fetch(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'orderbook' AND table_name = 'raw_events'"
        )
        cols = {r["column_name"]: r for r in rows}
        assert cols["ts"]["data_type"] == "timestamp with time zone"
        assert cols["payload"]["data_type"] == "jsonb"
        for ns_col in ("t_ingest_ns", "t_mono_ns", "t_event_ns", "vs_seq"):
            assert cols[ns_col]["data_type"] == "bigint"
        # Append-only raw: the venue-time + sequence columns are nullable.
        assert cols["t_event_ns"]["is_nullable"] == "YES"
        assert cols["vs_seq"]["is_nullable"] == "YES"
    finally:
        await conn.close()


async def test_price_columns_are_numeric_18_6(settings: Settings) -> None:
    """Prices are numeric(18,6) on trades + settlements; volume is bigint."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    try:
        rows = await conn.fetch(
            "SELECT table_name, column_name, data_type, numeric_precision, numeric_scale "
            "FROM information_schema.columns "
            "WHERE table_schema = 'orderbook' "
            "AND ((table_name = 'trades' AND column_name IN ('price', 'volume')) "
            "  OR (table_name = 'settlements' AND column_name = 'settlement_price'))"
        )
        cols = {(r["table_name"], r["column_name"]): r for r in rows}
        for key in (("trades", "price"), ("settlements", "settlement_price")):
            assert cols[key]["data_type"] == "numeric"
            assert cols[key]["numeric_precision"] == 18
            assert cols[key]["numeric_scale"] == 6
        assert cols[("trades", "volume")]["data_type"] == "bigint"
    finally:
        await conn.close()


async def test_market_and_grade_checks(settings: Settings) -> None:
    """CHECK constraints carry the market / quality-grade enum sets."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    try:
        constraints = await conn.fetch(
            "SELECT pg_get_constraintdef(c.oid) AS def FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE n.nspname = 'orderbook' AND c.contype = 'c'"
        )
        defs = " ".join(r["def"] for r in constraints)
        for token in ("'SET'", "'TFEX'", "'GREEN'", "'AMBER'", "'RED'", "'BUY'", "'SELL'"):
            assert token in defs
    finally:
        await conn.close()


async def test_read_indexes_exist(settings: Settings) -> None:
    """The (symbol, ts DESC) read indexes + the reference-table lookups exist."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    try:
        rows = await conn.fetch(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'orderbook'"
        )
        defs = {r["indexname"]: r["indexdef"] for r in rows}
        assert "(symbol, ts DESC)" in defs["idx_raw_events_symbol_ts"]
        assert "(symbol, ts DESC)" in defs["idx_trades_symbol_ts"]
        assert "(symbol, ts DESC)" in defs["idx_book_snapshots_symbol_ts"]
        assert "(symbol, date DESC)" in defs["idx_settlements_symbol_date"]
        assert "(symbol, wall_start, wall_end)" in defs["idx_gap_windows_symbol_wall"]
    finally:
        await conn.close()


async def test_compression_and_retention_policies(settings: Settings) -> None:
    """Each hypertable has a compression policy + a provisional retention policy."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    try:
        rows = await conn.fetch(
            "SELECT hypertable_name, proc_name FROM timescaledb_information.jobs "
            "WHERE hypertable_schema = 'orderbook'"
        )
        by_table: dict[str, set[str]] = {}
        for r in rows:
            by_table.setdefault(r["hypertable_name"], set()).add(r["proc_name"])
        for ht in HYPERTABLES:
            assert "policy_compression" in by_table.get(ht, set()), ht
            assert "policy_retention" in by_table.get(ht, set()), ht
    finally:
        await conn.close()


async def test_raw_events_decimal_and_jsonb_roundtrip(settings: Settings) -> None:
    """raw_events stores the ns timestamps + a JSONB payload; vs_seq may be NULL."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        payload = json.dumps({"room": 12345, "bp": ["912.400000"], "bv": [10]})
        await conn.execute(INSERT_RAW_EVENT, "S50M26", None, payload, 1, 2)
        row = await conn.fetchrow(
            "SELECT vs_seq, payload, t_ingest_ns FROM orderbook.raw_events WHERE symbol = $1",
            "S50M26",
        )
        assert row is not None
        assert row["vs_seq"] is None  # nullable — not every namespace carries one
        assert json.loads(row["payload"])["room"] == 12345
        assert row["t_ingest_ns"] == 1
    finally:
        await tr.rollback()
        await conn.close()


async def test_settlement_price_roundtrips_decimal_and_upserts(settings: Settings) -> None:
    """settlements price is Decimal-exact and (date, symbol) upserts idempotently."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        d = date(2026, 6, 15)
        await conn.execute(INSERT_SETTLEMENT, d, "S50M26", Decimal("912.400000"))
        # Re-emit the same key with a corrected price — ON CONFLICT updates, no dup row.
        await conn.execute(INSERT_SETTLEMENT, d, "S50M26", Decimal("913.100000"))
        stored = await conn.fetchval(
            "SELECT settlement_price FROM orderbook.settlements WHERE date = $1 AND symbol = $2",
            d,
            "S50M26",
        )
        assert isinstance(stored, Decimal)
        assert stored == Decimal("913.100000")
        count = await conn.fetchval(
            "SELECT count(*) FROM orderbook.settlements WHERE date = $1 AND symbol = $2",
            d,
            "S50M26",
        )
        assert count == 1
    finally:
        await tr.rollback()
        await conn.close()


async def test_gap_windows_identity_pk(settings: Settings) -> None:
    """gap_windows auto-assigns its identity PK on insert."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        gap_id = await conn.fetchval(
            "INSERT INTO orderbook.gap_windows "
            "(symbol, market, from_vs, to_vs, missing_count, wall_start, wall_end) "
            "VALUES ('S50M26', 'TFEX', 100, 105, 4, now(), now()) RETURNING gap_id"
        )
        assert isinstance(gap_id, int)
    finally:
        await tr.rollback()
        await conn.close()


async def test_quant_role_has_least_privilege_grants(settings: Settings) -> None:
    """quant has USAGE on the schema + the documented per-table grants, no DELETE."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    try:
        usage = await conn.fetchval("SELECT has_schema_privilege('quant', 'orderbook', 'USAGE')")
        assert usage is True
        for tbl in ("raw_events", "trades", "book_snapshots", "gap_windows"):
            assert await conn.fetchval(
                f"SELECT has_table_privilege('quant', 'orderbook.{tbl}', 'INSERT')"
            )
            assert await conn.fetchval(
                f"SELECT has_table_privilege('quant', 'orderbook.{tbl}', 'SELECT')"
            )
            # Append-only event/audit tables: no DELETE.
            assert not await conn.fetchval(
                f"SELECT has_table_privilege('quant', 'orderbook.{tbl}', 'DELETE')"
            )
        # Upsert tables need UPDATE for ON CONFLICT DO UPDATE.
        for tbl in ("settlements", "dq_manifests"):
            assert await conn.fetchval(
                f"SELECT has_table_privilege('quant', 'orderbook.{tbl}', 'UPDATE')"
            )
            assert not await conn.fetchval(
                f"SELECT has_table_privilege('quant', 'orderbook.{tbl}', 'DELETE')"
            )
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# orderbook.greeks tests (15_orderbook_greeks.sql)
# ---------------------------------------------------------------------------


async def test_greeks_table_exists(settings: Settings) -> None:
    """orderbook.greeks exists as a plain (non-hypertable) table."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    try:
        table = await conn.fetchval(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'orderbook' AND table_name = 'greeks'"
        )
        assert table == "greeks"
    finally:
        await conn.close()


async def test_greeks_columns(settings: Settings) -> None:
    """orderbook.greeks has the expected columns, types, and nullable/not-null constraints."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    try:
        rows = await conn.fetch(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'orderbook' AND table_name = 'greeks'"
        )
        cols = {r["column_name"]: r for r in rows}

        # NOT NULL columns.
        for col in (
            "date",
            "symbol",
            "series",
            "is_call",
            "strike",
            "underlying_symbol",
            "forward",
            "option_price",
            "source",
        ):
            assert cols[col]["is_nullable"] == "NO", f"{col} should be NOT NULL"

        # Nullable Greeks / solver outputs.
        for col in ("time_to_expiry", "iv", "delta", "gamma", "vega", "theta", "rate"):
            assert cols[col]["is_nullable"] == "YES", f"{col} should be nullable"

        # Type checks on key columns.
        assert cols["date"]["data_type"] == "date"
        assert cols["symbol"]["data_type"] == "text"
        assert cols["is_call"]["data_type"] == "boolean"
        assert cols["strike"]["data_type"] == "numeric"
        assert cols["forward"]["data_type"] == "numeric"
        assert cols["option_price"]["data_type"] == "numeric"
        assert cols["iv"]["data_type"] == "numeric"
        assert cols["source"]["data_type"] == "text"
    finally:
        await conn.close()


async def test_greeks_primary_key(settings: Settings) -> None:
    """pk_greeks is on (date, symbol); re-insert with same key upserts idempotently."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        insert = (
            "INSERT INTO orderbook.greeks "
            "(date, symbol, series, is_call, strike, underlying_symbol, "
            " forward, option_price, source) "
            "VALUES ($1, $2, 'M26', TRUE, 1000.0, 'S50M26', 920.0, 10.5, 'black76') "
            "ON CONFLICT (date, symbol) DO UPDATE "
            "SET option_price = EXCLUDED.option_price"
        )
        d = date(2026, 6, 16)
        await conn.execute(insert, d, "S50M26C1000")
        # Re-insert same (date, symbol) with different option_price — must upsert, not duplicate.
        await conn.execute(insert, d, "S50M26C1000")
        count = await conn.fetchval(
            "SELECT count(*) FROM orderbook.greeks WHERE date = $1 AND symbol = $2",
            d,
            "S50M26C1000",
        )
        assert count == 1
    finally:
        await tr.rollback()
        await conn.close()


async def test_greeks_nullable_iv_roundtrip(settings: Settings) -> None:
    """iv and all Greeks columns accept NULL (below-intrinsic / unsolvable case)."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        await conn.execute(
            "INSERT INTO orderbook.greeks "
            "(date, symbol, series, is_call, strike, underlying_symbol, "
            " forward, option_price, time_to_expiry, iv, delta, gamma, vega, theta, rate, source) "
            "VALUES ($1, $2, 'M26', FALSE, 1100.0, 'S50M26', 920.0, 0.5, "
            "        0.04, NULL, NULL, NULL, NULL, NULL, 0.02, 'black76')",
            date(2026, 6, 16),
            "S50M26P1100",
        )
        row = await conn.fetchrow(
            "SELECT iv, delta, gamma, vega, theta FROM orderbook.greeks WHERE symbol = $1",
            "S50M26P1100",
        )
        assert row is not None
        assert row["iv"] is None
        assert row["delta"] is None
        assert row["gamma"] is None
        assert row["vega"] is None
        assert row["theta"] is None
    finally:
        await tr.rollback()
        await conn.close()


async def test_greeks_index_exists(settings: Settings) -> None:
    """ix_greeks_symbol_date index exists on (symbol, date DESC)."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    try:
        rows = await conn.fetch(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'orderbook'"
        )
        defs = {r["indexname"]: r["indexdef"] for r in rows}
        assert "ix_greeks_symbol_date" in defs
        assert "(symbol, date DESC)" in defs["ix_greeks_symbol_date"]
    finally:
        await conn.close()


async def test_greeks_quant_grants(settings: Settings) -> None:
    """quant has SELECT, INSERT, UPDATE on orderbook.greeks; no DELETE."""
    import asyncpg

    conn = await asyncpg.connect(settings.orderbook_dsn)
    try:
        assert await conn.fetchval(
            "SELECT has_table_privilege('quant', 'orderbook.greeks', 'SELECT')"
        )
        assert await conn.fetchval(
            "SELECT has_table_privilege('quant', 'orderbook.greeks', 'INSERT')"
        )
        assert await conn.fetchval(
            "SELECT has_table_privilege('quant', 'orderbook.greeks', 'UPDATE')"
        )
        assert not await conn.fetchval(
            "SELECT has_table_privilege('quant', 'orderbook.greeks', 'DELETE')"
        )
    finally:
        await conn.close()
