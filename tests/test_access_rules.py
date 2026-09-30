"""The TK-0621 access restriction, pinned so a regression fails CI instead of reopening the LAN.

Operator ruling 2026-09-29: restrict who can reach HOME's Postgres and Mongo, without rotating any
credential. The rules live in files this repo owns, so they are checked here, statically:
``config/pg_hba.conf`` (installed by ``scripts/apply_pg_hba.sh``) and ``docker-compose.yml``.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HBA = ROOT / "config" / "pg_hba.conf"
COMPOSE = ROOT / "docker-compose.yml"

#: Addresses allowed to reach a password or trust rule. Loopback is the container's own; the /16 is
#: quant-network (every container, and HOME host processes arriving via Docker's proxy at .1).
ALLOWED = {"127.0.0.1/32", "::1/128", "172.25.0.0/16"}


def _rules() -> list[list[str]]:
    lines = HBA.read_text(encoding="utf-8").splitlines()
    return [ln.split() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def _service_block(name: str) -> list[str]:
    """The lines of one service in docker-compose.yml, read by indentation (no YAML dependency)."""
    out: list[str] = []
    inside = False
    for ln in COMPOSE.read_text(encoding="utf-8").splitlines():
        if ln.startswith("  ") and not ln.startswith("    ") and ln.strip().endswith(":"):
            inside = ln.strip() == f"{name}:"
            continue
        if ln and not ln.startswith(" "):
            inside = False
        if inside:
            out.append(ln)
    return out


def test_every_admitting_host_rule_is_on_the_allowed_list() -> None:
    admitting = [r for r in _rules() if r[0] == "host" and r[-1] != "reject"]
    assert admitting, "no host rule admits anything; every container would be refused"
    for r in admitting:
        rule = " ".join(r)
        assert r[3] in ALLOWED, f"pg_hba admits {r[3]} ({rule}); allowed: {sorted(ALLOWED)}"


def test_no_rule_admits_every_address() -> None:
    for r in _rules():
        if r[0] == "host" and r[-1] != "reject":
            assert r[3] not in {"all", "0.0.0.0/0", "::/0"}, f"wide-open rule: {' '.join(r)}"
            net = ipaddress.ip_network(r[3], strict=False)
            assert net.num_addresses <= 2**16, f"{r[3]} is wider than quant-network's /16"


def test_the_file_ends_by_refusing_both_address_families() -> None:
    tail = [(r[3], r[-1]) for r in _rules()[-2:]]
    assert tail == [("0.0.0.0/0", "reject"), ("::/0", "reject")], tail


def test_exactly_one_password_subnet_so_the_apply_script_can_check_it() -> None:
    scram = [r[3] for r in _rules() if r[0] == "host" and r[-1] == "scram-sha-256"]
    assert scram == ["172.25.0.0/16"], scram


def test_the_in_container_rules_are_unchanged_from_the_image() -> None:
    loopback = {"127.0.0.1/32", "::1/128"}
    local = [" ".join(r) for r in _rules() if r[0] == "local" or r[3] in loopback]
    assert local == [
        "local all all trust",
        "host all all 127.0.0.1/32 trust",
        "host all all ::1/128 trust",
        "local replication all trust",
        "host replication all 127.0.0.1/32 trust",
        "host replication all ::1/128 trust",
    ]


def test_mongo_publishes_no_host_port() -> None:
    block = _service_block("mongodb")
    assert block, "mongodb service not found; the block reader is broken, not the rule"
    published = any(ln.startswith("    ports:") for ln in block)
    assert not published, "quant-mongo is published on the host again"


def test_the_block_reader_sees_postgres_ports() -> None:
    """Positive control: the same reader DOES find a published port, so the Mongo test can fail."""
    assert any(ln.startswith("    ports:") for ln in _service_block("postgres"))
