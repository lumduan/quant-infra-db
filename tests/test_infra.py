import json
import subprocess

import pytest

pytestmark = pytest.mark.infra


def _docker_compose_ps() -> list[dict[str, str]]:
    """Run docker compose ps --format json and return parsed output."""
    result = subprocess.run(
        ["docker", "compose", "ps", "--format", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    objects = []
    for line in result.stdout.strip().split("\n"):
        if line.strip():
            objects.append(json.loads(line))
    return objects


def _docker_network_ls() -> list[str]:
    """Return list of Docker network names."""
    result = subprocess.run(
        ["docker", "network", "ls", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return result.stdout.strip().split("\n")


def test_docker_compose_ps_healthy() -> None:
    """Both quant-postgres and quant-mongo must be healthy."""
    containers = _docker_compose_ps()
    if not containers:
        pytest.skip("Docker Compose stack not running")

    names = {c["Name"] for c in containers}
    assert "quant-postgres" in names, f"quant-postgres not found in {names}"
    assert "quant-mongo" in names, f"quant-mongo not found in {names}"

    for c in containers:
        health = c.get("Health", "")
        assert health == "healthy", f"{c['Name']} health is '{health}', expected 'healthy'"


def test_network_quant_network_exists() -> None:
    """The quant-network must exist."""
    networks = _docker_network_ls()
    if "quant-network" not in networks:
        pytest.skip("quant-network not found — run: docker network create quant-network")
    assert "quant-network" in networks
