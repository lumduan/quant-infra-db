"""Live-DB tests for the crypto capture store (20_schema_crypto.sql + 21_crypto_dq.sql).

Phase 1 of feature-crypto-engine: the durable hot-tier mirror for the 24/7 Crypto
Capture engine (Binance TH + Bitkub). Covers idempotent re-apply, the crypto schema
+ its tables, hypertable membership for the three streams, plain-table status for
the DQ tables, the crypto NUMERIC precision (price 20,8 / size 28,10 — the fractional
deviation from the SET/TFEX bigint volume, ADR CX11), dual-timestamp nullability
(ADR CX3), the venue / grade / side / update_type CHECK sets, the read indexes,
idempotent dq_manifests upsert, gap_windows identity PK, the least-privilege quant
grants, and the read-only monitor grant.

Run with a live stack: uv run pytest -m infra
"""

import json
import subprocess
from datetime import date
from decimal import Decimal

import pytest
from src.config import Settings

pytestmark = pytest.mark.infra

HYPERTABLES = ("raw_events", "trades", "book_updates")
PLAIN_TABLES = ("dq_manifests", "gap_windows")
ALL_TABLES = HYPERTABLES + PLAIN_TABLES

INSERT_TRADE = (
    "INSERT INTO crypto.trades "
    "(ts, venue, source, symbol, price, size, side, trade_id, is_buyer_maker, "
    " exchange_ts_ms, local_ts_us, t_ingest_ns, t_mono_ns) "
    "VALUES (now(), 'binance_th', 'binance_th', $1, $2, $3, 'sell', 8811447, TRUE, "
    "        1783406481258, 1783406481314656, $4, $5)"
)
INSERT_BITKUB_TRADE = (
    "INSERT INTO crypto.trades "
    "(ts, venue, source, symbol, price, size, side, trade_id, is_buyer_maker, "
    " exchange_ts_ms, local_ts_us, t_ingest_ns, t_mono_ns) "
    "VALUES (now(), 'bitkub', 'bitkub', $1, $2, $3, 'buy', NULL, NULL, "
    "        NULL, 1783406472816888, $4, $5)"
)
INSERT_MANIFEST = (
    "INSERT INTO crypto.dq_manifests (date, source, quality_grade, manifest_json) "
    "VALUES ($1, $2, $3, $4::jsonb) "
    "ON CONFLICT (date, source) DO UPDATE SET quality_grade = EXCLUDED.quality_grade"
)


@pytest.fixture
def settings() -> Settings:
    """Load settings from the real .env file (requires .env with valid POSTGRES_PASSWORD)."""
    return Settings()


def _crypto_dsn(settings: Settings) -> str:
    """Derive the db_crypto DSN from the orderbook DSN (same host/creds, different db)."""
    return settings.orderbook_dsn.replace("db_orderbook", "db_crypto")


def test_schema_reapply_idempotent() -> None:
    """01 + 02 + 20 + 21 apply cleanly against the live container — twice (2nd run is a no-op).

    Runs first: it also bootstraps db_crypto on a stack whose volume predates the
    scripts (init-scripts only auto-run on a fresh volume). ON_ERROR_STOP=1 is
    mandatory — without it psql exits 0 even on errors.
    """
    for _ in range(2):
        for script in (
            "01_create_databases.sql",
            "02_enable_timescaledb.sql",
            "20_schema_crypto.sql",
            "21_crypto_dq.sql",
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
                check=False,
            )
            assert result.returncode == 0, f"{script} failed:\n{result.stderr}"


async def test_crypto_db_reachable(settings: Settings) -> None:
    """db_crypto is reachable and carries the crypto schema + timescaledb."""
    import asyncpg

    conn = await asyncpg.connect(_crypto_dsn(settings))
    try:
        assert await conn.fetchval("SELECT 1") == 1
        schema = await conn.fetchval(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'crypto'"
        )
        assert schema == "crypto"
        assert await conn.fetchval("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'") == 1
    finally:
        await conn.close()


async def test_crypto_tables_exist(settings: Settings) -> None:
    """All five crypto tables exist."""
    import asyncpg

    conn = await asyncpg.connect(_crypto_dsn(settings))
    try:
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'crypto'"
        )
        assert set(ALL_TABLES) <= {r["table_name"] for r in rows}
    finally:
        await conn.close()


async def test_event_streams_are_hypertables(settings: Settings) -> None:
    """raw_events / trades / book_updates are hypertables; the DQ tables are plain."""
    import asyncpg

    conn = await asyncpg.connect(_crypto_dsn(settings))
    try:
        rows = await conn.fetch(
            "SELECT hypertable_name FROM timescaledb_information.hypertables "
            "WHERE hypertable_schema = 'crypto'"
        )
        hypertables = {r["hypertable_name"] for r in rows}
        assert set(HYPERTABLES) <= hypertables
        for plain in PLAIN_TABLES:
            assert plain not in hypertables
    finally:
        await conn.close()


async def test_trade_price_and_size_precision(settings: Settings) -> None:
    """price is NUMERIC(20,8); size is the FRACTIONAL NUMERIC(28,10) (ADR CX11), not bigint."""
    import asyncpg

    conn = await asyncpg.connect(_crypto_dsn(settings))
    try:
        rows = await conn.fetch(
            "SELECT column_name, data_type, numeric_precision, numeric_scale "
            "FROM information_schema.columns "
            "WHERE table_schema = 'crypto' AND table_name = 'trades' "
            "AND column_name IN ('price', 'size')"
        )
        cols = {r["column_name"]: r for r in rows}
        assert cols["price"]["data_type"] == "numeric"
        assert (cols["price"]["numeric_precision"], cols["price"]["numeric_scale"]) == (20, 8)
        assert cols["size"]["data_type"] == "numeric"
        assert (cols["size"]["numeric_precision"], cols["size"]["numeric_scale"]) == (28, 10)
    finally:
        await conn.close()


async def test_dual_timestamp_nullability(settings: Settings) -> None:
    """exchange_ts_ms is nullable (Bitkub depth has none, ADR CX3); local_ts_us is NOT NULL."""
    import asyncpg

    conn = await asyncpg.connect(_crypto_dsn(settings))
    try:
        for tbl in ("trades", "book_updates", "raw_events"):
            rows = await conn.fetch(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'crypto' AND table_name = $1 "
                "AND column_name IN ('exchange_ts_ms', 'local_ts_us')",
                tbl,
            )
            cols = {r["column_name"]: r["is_nullable"] for r in rows}
            assert cols["exchange_ts_ms"] == "YES", tbl
            assert cols["local_ts_us"] == "NO", tbl
    finally:
        await conn.close()


async def test_check_constraint_enums(settings: Settings) -> None:
    """CHECK constraints carry the venue / grade / side / update_type enum sets."""
    import asyncpg

    conn = await asyncpg.connect(_crypto_dsn(settings))
    try:
        constraints = await conn.fetch(
            "SELECT pg_get_constraintdef(c.oid) AS def FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE n.nspname = 'crypto' AND c.contype = 'c'"
        )
        defs = " ".join(r["def"] for r in constraints)
        for token in (
            "'binance_th'",
            "'binance_global'",
            "'bitkub'",
            "'GREEN'",
            "'AMBER'",
            "'RED'",
            "'buy'",
            "'sell'",
            "'diff'",
            "'snapshot'",
        ):
            assert token in defs, token
    finally:
        await conn.close()


async def test_read_indexes_exist(settings: Settings) -> None:
    """The trades read indexes exist: (symbol, ts DESC) + (venue, symbol, ts DESC)."""
    import asyncpg

    conn = await asyncpg.connect(_crypto_dsn(settings))
    try:
        rows = await conn.fetch(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'crypto'"
        )
        defs = {r["indexname"]: r["indexdef"] for r in rows}
        assert "(symbol, ts DESC)" in defs["idx_crypto_trades_sym_ts"]
        assert "(venue, symbol, ts DESC)" in defs["idx_crypto_trades_venue_sym_ts"]
    finally:
        await conn.close()


async def test_compression_and_retention_policies(settings: Settings) -> None:
    """Each hypertable has a compression policy + a provisional retention policy."""
    import asyncpg

    conn = await asyncpg.connect(_crypto_dsn(settings))
    try:
        rows = await conn.fetch(
            "SELECT hypertable_name, proc_name FROM timescaledb_information.jobs "
            "WHERE hypertable_schema = 'crypto'"
        )
        by_table: dict[str, set[str]] = {}
        for r in rows:
            by_table.setdefault(r["hypertable_name"], set()).add(r["proc_name"])
        for ht in HYPERTABLES:
            assert "policy_compression" in by_table.get(ht, set()), ht
            assert "policy_retention" in by_table.get(ht, set()), ht
    finally:
        await conn.close()


async def test_fractional_size_roundtrips_decimal(settings: Settings) -> None:
    """A satoshi-scale fractional size (5.2e-06) round-trips Decimal-exact (ADR CX11)."""
    import asyncpg

    conn = await asyncpg.connect(_crypto_dsn(settings))
    tr = conn.transaction()
    await tr.start()
    try:
        await conn.execute(
            INSERT_TRADE, "BTC/THB", Decimal("2106692.09"), Decimal("0.0000052"), 1, 2
        )
        row = await conn.fetchrow(
            "SELECT price, size, exchange_ts_ms FROM crypto.trades WHERE symbol = $1", "BTC/THB"
        )
        assert row is not None
        assert isinstance(row["size"], Decimal)
        assert row["size"] == Decimal("0.0000052000")
        assert row["price"] == Decimal("2106692.09000000")
        assert row["exchange_ts_ms"] == 1783406481258
    finally:
        await tr.rollback()
        await conn.close()


async def test_bitkub_trade_allows_null_clock_and_ids(settings: Settings) -> None:
    """A Bitkub trade stores NULL exchange_ts_ms + NULL trade_id (degraded, ADR CX3/CX4)."""
    import asyncpg

    conn = await asyncpg.connect(_crypto_dsn(settings))
    tr = conn.transaction()
    await tr.start()
    try:
        await conn.execute(
            INSERT_BITKUB_TRADE, "USDT/THB", Decimal("33.28"), Decimal("42400"), 1, 2
        )
        row = await conn.fetchrow(
            "SELECT exchange_ts_ms, trade_id, local_ts_us FROM crypto.trades WHERE symbol = $1",
            "USDT/THB",
        )
        assert row is not None
        assert row["exchange_ts_ms"] is None
        assert row["trade_id"] is None
        assert row["local_ts_us"] == 1783406472816888
    finally:
        await tr.rollback()
        await conn.close()


async def test_dq_manifest_upserts_idempotently(settings: Settings) -> None:
    """dq_manifests (date, source) upserts — a re-graded day updates, never duplicates."""
    import asyncpg

    conn = await asyncpg.connect(_crypto_dsn(settings))
    tr = conn.transaction()
    await tr.start()
    try:
        d = date(2026, 7, 7)
        await conn.execute(INSERT_MANIFEST, d, "binance_th", "AMBER", json.dumps({"gaps": 1}))
        await conn.execute(INSERT_MANIFEST, d, "binance_th", "GREEN", json.dumps({"gaps": 0}))
        grade = await conn.fetchval(
            "SELECT quality_grade FROM crypto.dq_manifests WHERE date = $1 AND source = $2",
            d,
            "binance_th",
        )
        count = await conn.fetchval(
            "SELECT count(*) FROM crypto.dq_manifests WHERE date = $1 AND source = $2",
            d,
            "binance_th",
        )
        assert grade == "GREEN"
        assert count == 1
    finally:
        await tr.rollback()
        await conn.close()


async def test_gap_windows_identity_pk(settings: Settings) -> None:
    """gap_windows auto-assigns its identity PK; from_seq may be NULL (Bitkub degraded)."""
    import asyncpg

    conn = await asyncpg.connect(_crypto_dsn(settings))
    tr = conn.transaction()
    await tr.start()
    try:
        gap_id = await conn.fetchval(
            "INSERT INTO crypto.gap_windows "
            "(date, source, symbol, stream, from_seq, to_seq, missing_count, wall_start, wall_end) "
            "VALUES ($1, 'bitkub', 'BTC/THB', 'depth', NULL, NULL, NULL, now(), now()) "
            "RETURNING gap_id",
            date(2026, 7, 7),
        )
        assert isinstance(gap_id, int)
    finally:
        await tr.rollback()
        await conn.close()


async def test_quant_role_has_least_privilege_grants(settings: Settings) -> None:
    """quant has USAGE + the documented per-table grants, no DELETE anywhere."""
    import asyncpg

    conn = await asyncpg.connect(_crypto_dsn(settings))
    try:
        assert await conn.fetchval("SELECT has_schema_privilege('quant', 'crypto', 'USAGE')")
        for tbl in ("raw_events", "trades", "book_updates", "gap_windows"):
            assert await conn.fetchval(
                f"SELECT has_table_privilege('quant', 'crypto.{tbl}', 'INSERT')"
            )
            assert await conn.fetchval(
                f"SELECT has_table_privilege('quant', 'crypto.{tbl}', 'SELECT')"
            )
            assert not await conn.fetchval(
                f"SELECT has_table_privilege('quant', 'crypto.{tbl}', 'DELETE')"
            )
        # dq_manifests needs UPDATE for the ON CONFLICT DO UPDATE upsert; still no DELETE.
        assert await conn.fetchval(
            "SELECT has_table_privilege('quant', 'crypto.dq_manifests', 'UPDATE')"
        )
        assert not await conn.fetchval(
            "SELECT has_table_privilege('quant', 'crypto.dq_manifests', 'DELETE')"
        )
    finally:
        await conn.close()


async def test_monitor_role_is_read_only_crypto(settings: Settings) -> None:
    """monitor has USAGE + SELECT on crypto.*, and NO write privileges (21_crypto_dq.sql)."""
    import asyncpg

    conn = await asyncpg.connect(_crypto_dsn(settings))
    try:
        assert await conn.fetchval("SELECT has_schema_privilege('monitor', 'crypto', 'USAGE')")
        for tbl in ("raw_events", "trades", "book_updates", "dq_manifests"):
            assert await conn.fetchval(
                f"SELECT has_table_privilege('monitor', 'crypto.{tbl}', 'SELECT')"
            )
            for priv in ("INSERT", "UPDATE", "DELETE"):
                assert not await conn.fetchval(
                    f"SELECT has_table_privilege('monitor', 'crypto.{tbl}', '{priv}')"
                )
    finally:
        await conn.close()
