"""Live-DB tests for the execution order store (12_schema_execution.sql).

Phase 1 of feature-execution-engine: durable, idempotent, auditable order
store. Covers idempotent re-apply, the client_order_id idempotency PK, the
frozen 9-state transition guard, the trigger-written append-only audit trail,
fill dedupe, and numeric precision.

Run with a live stack: uv run pytest -m infra
"""

import json
import subprocess
from decimal import Decimal

import pytest
from src.config import Settings

pytestmark = pytest.mark.infra

ALL_STATUSES = (
    "PENDING_NEW",
    "NEW",
    "PARTIALLY_FILLED",
    "FILLED",
    "PENDING_CANCEL",
    "PENDING_REPLACE",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
)
ALL_ORDER_TYPES = ("MARKET", "LIMIT", "STOP", "STOP_LIMIT", "ICEBERG", "MTL", "ATO", "ATC")
ALL_BROKERS = ("sim", "liberator", "settrade")

INSERT_ORDER = (
    "INSERT INTO execution.orders "
    "(client_order_id, broker, account, symbol, market, side, order_type, price, quantity, tif) "
    "VALUES ($1, 'sim', 'ACC-TEST', 'PTT', 'SET', 'BUY', 'LIMIT', 123.456789, 100, 'DAY')"
)
SET_STATUS = "UPDATE execution.orders SET status = $2 WHERE client_order_id = $1"
COUNT_EVENTS = "SELECT count(*) FROM execution.order_events WHERE client_order_id = $1"


@pytest.fixture
def settings() -> Settings:
    """Load settings from the real .env file (requires .env with valid POSTGRES_PASSWORD)."""
    return Settings()


def test_schema_reapply_idempotent() -> None:
    """01 + 12 apply cleanly against the live container — twice (second run is a no-op).

    Runs first in this module: it also bootstraps db_execution on a stack whose
    volume predates the script (init-scripts only auto-run on a fresh volume).
    ON_ERROR_STOP=1 is mandatory — without it psql exits 0 even on errors.
    """
    for _ in range(2):
        for script in (
            "01_create_databases.sql",
            "12_schema_execution.sql",
            "13_execution_strategy_id.sql",
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


async def test_execution_db_reachable(settings: Settings) -> None:
    """db_execution is reachable and carries the execution schema."""
    import asyncpg

    conn = await asyncpg.connect(settings.execution_dsn)
    try:
        assert await conn.fetchval("SELECT 1") == 1
        schema = await conn.fetchval(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'execution'"
        )
        assert schema == "execution"
    finally:
        await conn.close()


async def test_execution_has_no_timescaledb(settings: Settings) -> None:
    """db_execution deliberately runs plain tables — no timescaledb extension."""
    import asyncpg

    conn = await asyncpg.connect(settings.execution_dsn)
    try:
        row = await conn.fetchrow("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")
        assert row is None
    finally:
        await conn.close()


async def test_execution_tables_exist(settings: Settings) -> None:
    """orders, fills and order_events exist in the execution schema."""
    import asyncpg

    conn = await asyncpg.connect(settings.execution_dsn)
    try:
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'execution'"
        )
        tables = {r["table_name"] for r in rows}
        assert {"orders", "fills", "order_events"} <= tables
    finally:
        await conn.close()


async def test_orders_columns_types_and_checks(settings: Settings) -> None:
    """orders columns match the frozen contract: numeric(18,6) prices, bigint qty, timestamptz."""
    import asyncpg

    conn = await asyncpg.connect(settings.execution_dsn)
    try:
        rows = await conn.fetch(
            "SELECT column_name, data_type, numeric_precision, numeric_scale "
            "FROM information_schema.columns "
            "WHERE table_schema = 'execution' AND table_name = 'orders'"
        )
        cols = {r["column_name"]: r for r in rows}
        for price_col in ("price", "stop_price"):
            assert cols[price_col]["data_type"] == "numeric"
            assert cols[price_col]["numeric_precision"] == 18
            assert cols[price_col]["numeric_scale"] == 6
        for qty_col in ("quantity", "display_qty"):
            assert cols[qty_col]["data_type"] == "bigint"
        for ts_col in ("created_at", "updated_at"):
            assert cols[ts_col]["data_type"] == "timestamp with time zone"
        # Phase 2 addition: durable adapter/venue reject reason (nullable).
        assert cols["reject_reason"]["data_type"] == "text"

        # CHECK constraints carry the full frozen enum sets.
        constraints = await conn.fetch(
            "SELECT pg_get_constraintdef(c.oid) AS def FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE n.nspname = 'execution' AND t.relname = 'orders' AND c.contype = 'c'"
        )
        defs = " ".join(r["def"] for r in constraints)
        for value in ALL_STATUSES + ALL_ORDER_TYPES + ALL_BROKERS:
            assert f"'{value}'" in defs
        for token in ("'SET'", "'TFEX'", "'BUY'", "'SELL'", "'DAY'", "'IOC'", "'FOK'", "'GTC'"):
            assert token in defs
    finally:
        await conn.close()


async def test_orders_indexes_exist(settings: Settings) -> None:
    """The §B reconciliation index and the partial broker_order_id lookup exist."""
    import asyncpg

    conn = await asyncpg.connect(settings.execution_dsn)
    try:
        rows = await conn.fetch(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'execution'"
        )
        defs = {r["indexname"]: r["indexdef"] for r in rows}
        assert "(account, symbol, side, quantity, created_at)" in defs["idx_orders_reconcile"]
        assert "WHERE (broker_order_id IS NOT NULL)" in defs["idx_orders_broker_order_id"]
        assert "(client_order_id, event_id)" in defs["idx_order_events_order"]
    finally:
        await conn.close()


async def test_orders_strategy_id_column_and_index(settings: Settings) -> None:
    """Phase 5 addition: nullable text strategy_id + the partial stream-filter index.

    Strictly additive — rows insert fine without it (NULL), persist it when
    given, and the partial index excludes strategy-less rows.
    """
    import asyncpg

    conn = await asyncpg.connect(settings.execution_dsn)
    try:
        col = await conn.fetchrow(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'execution' AND table_name = 'orders' "
            "AND column_name = 'strategy_id'"
        )
        assert col is not None, "strategy_id column missing — apply 13_execution_strategy_id.sql"
        assert col["data_type"] == "text"
        assert col["is_nullable"] == "YES"

        idx = await conn.fetchval(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'execution' AND indexname = 'idx_orders_strategy'"
        )
        assert idx is not None
        assert "(strategy_id, created_at)" in idx
        assert "WHERE (strategy_id IS NOT NULL)" in idx

        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute(INSERT_ORDER, "T-EXEC-STRATEGY-00")  # no strategy_id -> NULL
            await conn.execute(
                "INSERT INTO execution.orders (client_order_id, broker, account, symbol, "
                "market, side, order_type, price, quantity, tif, strategy_id) "
                "VALUES ($1, 'sim', 'ACC-TEST', 'PTT', 'SET', 'BUY', 'LIMIT', 1.23, 100, "
                "'DAY', $2)",
                "T-EXEC-STRATEGY-01",
                "csm-set",
            )
            stamped = await conn.fetchval(
                "SELECT strategy_id FROM execution.orders WHERE client_order_id = $1",
                "T-EXEC-STRATEGY-01",
            )
            assert stamped == "csm-set"
            bare = await conn.fetchval(
                "SELECT strategy_id FROM execution.orders WHERE client_order_id = $1",
                "T-EXEC-STRATEGY-00",
            )
            assert bare is None
        finally:
            await tr.rollback()
    finally:
        await conn.close()


async def test_duplicate_client_order_id_rejected(settings: Settings) -> None:
    """The PK on client_order_id is the idempotency constraint — duplicates collide."""
    import asyncpg

    conn = await asyncpg.connect(settings.execution_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        cid = "T-EXEC-DUPLICATE-01"
        await conn.execute(INSERT_ORDER, cid)
        with pytest.raises(asyncpg.exceptions.UniqueViolationError):
            async with conn.transaction():
                await conn.execute(INSERT_ORDER, cid)
    finally:
        await tr.rollback()
        await conn.close()


async def test_insert_entry_state_enforced(settings: Settings) -> None:
    """Orders must enter at PENDING_NEW: explicit other states rejected, default applies."""
    import asyncpg

    conn = await asyncpg.connect(settings.execution_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO execution.orders (client_order_id, broker, account, symbol, "
                    "market, side, order_type, quantity, tif, status) "
                    "VALUES ('T-EXEC-ENTRY-NEW-1', 'sim', 'ACC-TEST', 'PTT', 'SET', 'BUY', "
                    "'MARKET', 100, 'DAY', 'NEW')"
                )
        cid = "T-EXEC-ENTRY-DEFAULT"
        await conn.execute(INSERT_ORDER, cid)
        status = await conn.fetchval(
            "SELECT status FROM execution.orders WHERE client_order_id = $1", cid
        )
        assert status == "PENDING_NEW"
    finally:
        await tr.rollback()
        await conn.close()


async def test_legal_lifecycle_appends_one_event_per_transition(settings: Settings) -> None:
    """PENDING_NEW → NEW → PARTIALLY_FILLED → FILLED succeeds with exactly 4 audit rows."""
    import asyncpg

    conn = await asyncpg.connect(settings.execution_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        cid = "T-EXEC-LIFECYCLE-01"
        await conn.execute(INSERT_ORDER, cid)
        # Ack: broker_order_id is persisted atomically with PENDING_NEW → NEW (ADR §B).
        await conn.execute(
            "UPDATE execution.orders SET status = 'NEW', broker_order_id = 'B-001' "
            "WHERE client_order_id = $1",
            cid,
        )
        await conn.execute(SET_STATUS, cid, "PARTIALLY_FILLED")
        # A same-status update (e.g. a second partial fill) must NOT append an event.
        await conn.execute(SET_STATUS, cid, "PARTIALLY_FILLED")
        await conn.execute(SET_STATUS, cid, "FILLED")

        events = await conn.fetch(
            "SELECT from_status, to_status, event FROM execution.order_events "
            "WHERE client_order_id = $1 ORDER BY event_id",
            cid,
        )
        assert [(r["from_status"], r["to_status"]) for r in events] == [
            (None, "PENDING_NEW"),
            ("PENDING_NEW", "NEW"),
            ("NEW", "PARTIALLY_FILLED"),
            ("PARTIALLY_FILLED", "FILLED"),
        ]
        ack_payload = json.loads(events[1]["event"])
        assert ack_payload["broker_order_id"] == "B-001"

        row = await conn.fetchrow(
            "SELECT created_at, updated_at FROM execution.orders WHERE client_order_id = $1", cid
        )
        assert row is not None
        # now() is transaction-fixed, so >= (not >) is the correct in-tx assertion.
        assert row["updated_at"] >= row["created_at"]
    finally:
        await tr.rollback()
        await conn.close()


async def test_illegal_transitions_rejected(settings: Settings) -> None:
    """Edges outside the frozen 13-edge graph are rejected and append no audit row."""
    import asyncpg

    conn = await asyncpg.connect(settings.execution_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        # Drive fixture orders to each non-terminal source state.
        fixtures = {
            "T-EXEC-ILL-PNEW-001": [],
            "T-EXEC-ILL-NEW-0001": ["NEW"],
            "T-EXEC-ILL-PCXL-001": ["NEW", "PENDING_CANCEL"],
            "T-EXEC-ILL-PRPL-001": ["NEW", "PENDING_REPLACE"],
        }
        for cid, path in fixtures.items():
            await conn.execute(INSERT_ORDER, cid)
            for state in path:
                await conn.execute(SET_STATUS, cid, state)

        illegal = [
            ("T-EXEC-ILL-PNEW-001", "FILLED"),
            ("T-EXEC-ILL-PNEW-001", "PARTIALLY_FILLED"),
            ("T-EXEC-ILL-PNEW-001", "CANCELLED"),
            ("T-EXEC-ILL-NEW-0001", "REJECTED"),  # not in the frozen graph
            ("T-EXEC-ILL-PCXL-001", "NEW"),
            ("T-EXEC-ILL-PRPL-001", "CANCELLED"),
        ]
        for cid, bad_state in illegal:
            before = await conn.fetchval(COUNT_EVENTS, cid)
            with pytest.raises(asyncpg.exceptions.CheckViolationError):
                async with conn.transaction():
                    await conn.execute(SET_STATUS, cid, bad_state)
            assert await conn.fetchval(COUNT_EVENTS, cid) == before
    finally:
        await tr.rollback()
        await conn.close()


async def test_terminal_states_immutable(settings: Settings) -> None:
    """Terminal states (FILLED / REJECTED / …) accept no further transition."""
    import asyncpg

    conn = await asyncpg.connect(settings.execution_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        rejected, filled = "T-EXEC-TERM-REJ-01", "T-EXEC-TERM-FIL-01"
        await conn.execute(INSERT_ORDER, rejected)
        await conn.execute(SET_STATUS, rejected, "REJECTED")
        await conn.execute(INSERT_ORDER, filled)
        await conn.execute(SET_STATUS, filled, "NEW")
        await conn.execute(SET_STATUS, filled, "FILLED")

        for cid, target in [
            (rejected, "NEW"),
            (rejected, "PENDING_NEW"),
            (rejected, "FILLED"),
            (filled, "CANCELLED"),
            (filled, "NEW"),
        ]:
            with pytest.raises(asyncpg.exceptions.CheckViolationError):
                async with conn.transaction():
                    await conn.execute(SET_STATUS, cid, target)
    finally:
        await tr.rollback()
        await conn.close()


async def test_fills_fk_and_dedupe(settings: Settings) -> None:
    """fills require a parent order; (client_order_id, broker_fill_id) dedupes redelivery."""
    import asyncpg

    insert_fill = (
        "INSERT INTO execution.fills (client_order_id, broker_fill_id, price, quantity, exec_ts) "
        "VALUES ($1, $2, 123.456789, 10, now())"
    )
    conn = await asyncpg.connect(settings.execution_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            async with conn.transaction():
                await conn.execute(insert_fill, "T-EXEC-NO-SUCH-ORDER", "F-1")

        cid = "T-EXEC-FILLS-000001"
        await conn.execute(INSERT_ORDER, cid)
        await conn.execute(insert_fill, cid, "F-1")
        with pytest.raises(asyncpg.exceptions.UniqueViolationError):
            async with conn.transaction():
                await conn.execute(insert_fill, cid, "F-1")  # at-least-once redelivery
        # NULL broker_fill_id rows are NOT deduped (NULLs are distinct) — documented
        # caveat: adapters must supply a fill id.
        await conn.execute(insert_fill, cid, None)
        await conn.execute(insert_fill, cid, None)
        count = await conn.fetchval(
            "SELECT count(*) FROM execution.fills WHERE client_order_id = $1", cid
        )
        assert count == 3
    finally:
        await tr.rollback()
        await conn.close()


async def test_order_events_append_only(settings: Settings) -> None:
    """order_events rejects UPDATE/DELETE/TRUNCATE; orders with events cannot be deleted."""
    import asyncpg

    conn = await asyncpg.connect(settings.execution_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        cid = "T-EXEC-APPEND-ONLY-1"
        await conn.execute(INSERT_ORDER, cid)

        with pytest.raises(asyncpg.exceptions.RaiseError):
            async with conn.transaction():
                await conn.execute(
                    "UPDATE execution.order_events SET to_status = 'NEW' "
                    "WHERE client_order_id = $1",
                    cid,
                )
        with pytest.raises(asyncpg.exceptions.RaiseError):
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM execution.order_events WHERE client_order_id = $1", cid
                )
        with pytest.raises(asyncpg.exceptions.RaiseError):
            async with conn.transaction():
                await conn.execute("TRUNCATE execution.order_events")
        # The audit chain protects its subject: the order itself cannot be deleted.
        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            async with conn.transaction():
                await conn.execute("DELETE FROM execution.orders WHERE client_order_id = $1", cid)
    finally:
        await tr.rollback()
        await conn.close()


async def test_numeric_price_roundtrips_decimal(settings: Settings) -> None:
    """numeric(18,6) prices round-trip Decimal exactly — no float anywhere."""
    import asyncpg

    conn = await asyncpg.connect(settings.execution_dsn)
    tr = conn.transaction()
    await tr.start()
    try:
        cid = "T-EXEC-DECIMAL-0001"
        price = Decimal("123.456789")
        await conn.execute(
            "INSERT INTO execution.orders (client_order_id, broker, account, symbol, market, "
            "side, order_type, price, quantity, tif) "
            "VALUES ($1, 'sim', 'ACC-TEST', 'S50H26', 'TFEX', 'BUY', 'LIMIT', $2, 5, 'DAY')",
            cid,
            price,
        )
        stored = await conn.fetchval(
            "SELECT price FROM execution.orders WHERE client_order_id = $1", cid
        )
        assert isinstance(stored, Decimal)
        assert stored == price
    finally:
        await tr.rollback()
        await conn.close()
