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

### Added (Phase 2 — PostgreSQL hardening)

- Idempotent database creation via `\gexec` pattern in `01_create_databases.sql`.
- Schema documentation: `docs/plans/phase_2_postgre_db/phase_2_postgresql_setup.md`.

### Added (Phase 3 — MongoDB hardening)

- MongoDB authentication support in `config.py` (`mongo_username`, `mongo_password`, `mongo_database`).
- Conditional auth in `mongo_uri` property — falls back to no-auth when credentials are empty.
- Hardened `mongo-init.js` with correct per-collection index fields (`version`, `date`) and comprehensive documentation.
- Expanded `test_mongo.py` index assertions to validate all three collections.
- Schema documentation: `docs/plans/phase_3_mongodb/phase_3_mongodb_setup.md`.

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
