# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (Phase 1)

- **Project Bootstrap:** Docker Compose stack (PostgreSQL + TimescaleDB + MongoDB) on `quant-network`.
- `docker-compose.yml` with healthchecks, named volumes, and external network configuration.
- Init scripts: `01_create_databases.sql`, `02_enable_timescaledb.sql`, `03_schema_csm_set.sql`, `04_schema_gateway.sql`, `mongo-init.js`.
- Python connectivity layer: Pydantic Settings config, asyncpg pool, motor client, typed exceptions.
- `scripts/backup.sh` for PostgreSQL (`pg_dumpall`) and MongoDB (`mongodump`).
- Unit tests (`test_config.py`) and integration tests (`test_postgres.py`, `test_mongo.py`, `test_infra.py`).
- Updated `README.md` with setup instructions, connection strings, and backup workflow.

### Changed

- Renamed project from `python-template` to `quant-infra-db`.
- Updated `.env.example` with PostgreSQL and MongoDB variables.

## [0.1.0] — 2026-05-06

### Added
- Initial template scaffold: `src/`, `tests/`, `docs/`, `.claude/`, `.github/`.
- `pyproject.toml` with `ruff`, `mypy`, `pytest`, `pytest-asyncio`, `pytest-cov`, `bandit`, `pip-audit`.
- Multi-stage `Dockerfile` (uv-native, Python 3.11-slim).
- CI workflow (lint, format check, type check, test with coverage) on Python 3.11 and 3.12.
- Docker publish workflow targeting GHCR.
- Weekly security scan workflow (`bandit` + `pip-audit`).
- AI-agent enablement: `.claude/knowledge/project-skill.md`, `.claude/playbooks/feature-development.md`, `.claude/prompts/Prompt-Engineer.prompt.md`.
- Issue templates (bug, feature), PR template, `FUNDING.yml`.

[Unreleased]: https://github.com/OWNER/REPO/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OWNER/REPO/releases/tag/v0.1.0
