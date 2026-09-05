"""🔒 Every table in an init script must GRANT to the app role — a STATIC guard.

This exists because `execution.fee_observations` shipped on 2026-09-04 with **no grant at
all**. It was appended *below* the file's grants block, which reads as exhaustive and is
not. `CREATE TABLE` runs as the superuser during init, so the app role `quant` would have
received zero privileges on it.

🔴 **Why that failure mode is worse than a plain permission error.** `information_schema`
filters by privilege. A role with no privileges on a table does not get "permission denied"
when it looks the table up — it gets **an empty result**, indistinguishable from the table
not existing. So the symptom is *"the migration didn't run"*, and the investigation starts
in the wrong place entirely.

These tests are deliberately **static** — they read the `.sql` files as text and take no
`infra` marker, so they run in ordinary CI. The live-DB tests in `test_execution_schema.py`
are skipped without a stack and could not have caught this.
"""

from __future__ import annotations

import re
from pathlib import Path

INIT_DIR = Path(__file__).resolve().parent.parent / "init-scripts"

_TABLE_RE = re.compile(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+([a-z_]+\.[a-z_]+)", re.I)
_GRANT_RE = re.compile(r"GRANT[^;]*?\bON\s+([a-z_]+\.[a-z_]+)", re.I)
_GRANT_ALL_RE = re.compile(r"GRANT[^;]*?ON ALL TABLES IN SCHEMA\s+([a-z_]+)", re.I)

# ⚠️ PRE-EXISTING, NOT INTRODUCED HERE, AND DELIBERATELY VISIBLE RATHER THAN IGNORED.
# `10_schema_market_data.sql` creates three tables and the file contains no GRANT of any
# kind; no other init script grants on `market_data` either. The LIVE databases do carry
# `quant=arwd` on all three, so the grants were applied out-of-band and the file has
# disagreed with reality ever since — a fresh volume init would produce the canonical OHLCV
# store with no app access. Filed rather than fixed: making a schema file grant something it
# never granted is a change to what a fresh install does, and that is not this PR's call.
KNOWN_UNGRANTED: frozenset[str] = frozenset(
    {
        "market_data.ohlcv",
        "market_data.universe_membership",
        "market_data.corporate_actions",
    }
)


def _ungranted_tables() -> set[str]:
    """Every `schema.table` created by an init script with no GRANT covering it."""
    missing: set[str] = set()
    for sql_file in sorted(INIT_DIR.glob("*.sql")):
        text = sql_file.read_text(encoding="utf-8")
        tables = set(_TABLE_RE.findall(text))
        granted = {t.lower() for t in _GRANT_RE.findall(text)}
        whole_schemas = {s.lower() for s in _GRANT_ALL_RE.findall(text)}
        for table in tables:
            name = table.lower()
            if name in granted or name.split(".")[0] in whole_schemas:
                continue
            missing.add(name)
    return missing


def test_no_NEW_table_ships_without_a_grant() -> None:
    """🔴 The regression guard. A new ungranted table is unusable and reads as ABSENT."""
    unexpected = _ungranted_tables() - KNOWN_UNGRANTED
    assert not unexpected, (
        f"{len(unexpected)} table(s) created with no GRANT: {sorted(unexpected)}. "
        "The app role would see these as NOT EXISTING, not as permission-denied. "
        "Add `GRANT ... TO quant;` beside the CREATE TABLE."
    )


def test_the_known_gap_list_is_not_STALE() -> None:
    """The allow-list must shrink when someone fixes one — otherwise it hides the next bug.

    Without this, `KNOWN_UNGRANTED` would silently keep excusing tables that have since
    been granted, and the exemption would outlive the reason for it.
    """
    stale = KNOWN_UNGRANTED - _ungranted_tables()
    assert not stale, (
        f"{sorted(stale)} now HAVE grants — remove them from KNOWN_UNGRANTED so the guard "
        "keeps covering them."
    )


def test_fee_observations_is_granted_and_APPEND_ONLY() -> None:
    """The specific table this file was written for, and the shape of its grant.

    Asserting only "a grant exists" would pass for `GRANT ALL`, which would let an
    observation be edited after the fact. The basis is an append-only dated series; evidence
    that can be UPDATEd is not evidence.
    """
    text = (INIT_DIR / "12_schema_execution.sql").read_text(encoding="utf-8")
    grants = [
        g.strip()
        for g in re.findall(r"(GRANT[^;]*?ON\s+execution\.fee_observations[^;]*);", text, re.I)
    ]
    assert len(grants) == 1, f"expected exactly one grant, found {len(grants)}: {grants}"
    granted = grants[0].upper()
    assert "SELECT" in granted and "INSERT" in granted
    assert "UPDATE" not in granted, "observations are append-only — no UPDATE"
    assert "DELETE" not in granted, "observations are append-only — no DELETE"
    assert " ALL " not in granted, "GRANT ALL would silently include UPDATE and DELETE"


def test_the_grant_follows_the_table_it_belongs_to() -> None:
    """Colocation is the actual fix; the grant existing somewhere is not enough.

    The original bug was ordering: the table was appended *after* a grants block that reads
    as complete. If the grant drifts back above the CREATE TABLE, the next table added at
    the end of the file reproduces the bug exactly.
    """
    text = (INIT_DIR / "12_schema_execution.sql").read_text(encoding="utf-8")
    create_at = text.index("CREATE TABLE IF NOT EXISTS execution.fee_observations")
    grant_at = text.index("GRANT SELECT, INSERT ON execution.fee_observations")
    assert grant_at > create_at, "the grant must sit BELOW its CREATE TABLE, not in the block above"
