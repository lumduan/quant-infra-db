# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project identity

`quant-infra-db` is the database infrastructure layer for the Quant Trading system.
It provisions **PostgreSQL + TimescaleDB** and **MongoDB** through Docker Compose
on a shared Docker network `quant-network`, consumed by downstream strategy services
and the API Gateway. The project is in early bootstrap (Phase 1 of the roadmap).

> Full roadmap: [docs/plans/ROADMAP.md](docs/plans/ROADMAP.md)

## Toolchain rule

**Every Python invocation MUST be prefixed with `uv run`.** Do not use `python`, `pip`, `poetry`, or `conda` directly — `uv` is the only supported package manager and runner. `uv.lock` is committed and authoritative.

```bash
uv sync --all-groups          # install (dev group included by default)
uv add <pkg>                  # runtime dep    (use --dev for dev group)
uv remove <pkg>
uv lock --upgrade-package <pkg> && uv sync
```

## Quality gate

All four must pass before commit and in CI:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
```

Coverage threshold of **80%** is enforced via `--cov-fail-under=80` in `pyproject.toml` (`tool.pytest.ini_options.addopts`) — failing coverage fails the test run, not just CI.

mypy runs in **strict** mode (`tool.mypy.strict = true`).

### Single test

```bash
uv run pytest tests/<path>::<test_name> -v
```

### Run app

```bash
uv run python -m src.main
```

### Security scans (also weekly in CI)

```bash
uv run bandit -r src
uv run pip-audit
```

## Architecture: Docker Compose stack

```
docker compose up -d
  └── quant-postgres  (timescale/timescaledb:latest-pg16)
  │     ├── db_csm_set   — equity_curve, trade_history, backtest_log
  │     └── db_gateway   — daily_performance, portfolio_snapshot
  └── quant-mongo    (mongo:latest)
        └── csm_logs — backtest_results, model_params, signal_snapshots
```

All containers join the external network `quant-network` (created once per host).
Downstream services reach databases by hostname (`quant-postgres`, `quant-mongo`),
not by IP address.

When the repo grows Python services, the one-way module flow applies:

```
External I/O → src/data → src/core → src/api → src/cli / src/main
                (fetch,    (business  (HTTP)    (entrypoints)
                 persist)   logic)
```

Entrypoint layers (`api/`, `cli/`, `main.py`) may import from `src/`; `src/` modules must NOT import from entrypoint layers.

## Docker Compose commands

```bash
docker compose up -d          # start the full stack
docker compose ps             # check status (should show healthy)
docker compose down           # stop everything
docker compose logs -f         # tail logs
docker exec -it quant-postgres psql -U postgres   # interactive psql
docker exec -it quant-mongo mongosh                # interactive mongosh
bash scripts/backup.sh        # backup PostgreSQL + MongoDB
```

## Directory structure

```
.
├── docker-compose.yml              # PostgreSQL + MongoDB core services
├── init-scripts/                   # Run on first container start
│   ├── 01_create_databases.sql
│   ├── 02_enable_timescaledb.sql
│   ├── 03_schema_csm_set.sql
│   ├── 04_schema_gateway.sql
│   └── mongo-init.js
├── scripts/
│   └── backup.sh                   # Backup PostgreSQL + MongoDB
├── .env.example                    # Credentials template
├── src/                            # Python source (thin; connectivity layer)
├── tests/                          # pytest suite
├── docs/
│   └── plans/
│       └── ROADMAP.md              # Master roadmap
├── .claude/                        # AI agent context & playbooks
├── .github/                        # CI/CD workflows, issue/PR templates
├── pyproject.toml                  # uv project config + tool settings
├── uv.lock                         # Locked dependency versions
└── README.md
```

## Hard rules (non-negotiable)

These come from `.claude/knowledge/project-skill.md` and are enforced by review:

1. **Async-first I/O.** All HTTP via `httpx.AsyncClient`. `requests` is **forbidden** in library code (sync, blocks event loop).
2. **Pydantic v2 at boundaries.** Data crossing module/process boundaries goes through Pydantic models — never raw dicts.
3. **Full type annotations** on every public function (args + return). No bare `Any` without justification.
4. **Errors:** define module-local exceptions in each subpackage's `errors.py`, all inheriting from a single root exception. Never `raise Exception(...)`; never `except Exception: pass`.
5. **Logging:** `logger = logging.getLogger(__name__)` at module top; use `%` formatting (`logger.info("processed %d items", n)`) for deferred interpolation, not f-strings. No `print` in library code. Never log secrets or full request bodies.
6. **Config via env vars** through `pydantic-settings` — no hard-coded paths; base paths come from a single `Settings` object. UTC for all stored timestamps.
7. **Conventional Commits:** `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`.
8. **No secrets in repo.** `.env` is gitignored; `.env.example` provides the template. Never commit real credentials.
9. **Docker Compose for infra.** Database services are managed via `docker compose`. Do not install PostgreSQL or MongoDB directly on the host.

## Soft conventions

- File size ≤ 500 lines; functions ≤ ~50 lines.
- Imports: stdlib → third-party → local, blank line between groups (ruff-isort enforces). No relative imports beyond one level. No wildcard imports.
- Tests mirror source paths one-to-one. `pytest-asyncio` is in `auto` mode (`asyncio_mode = "auto"`) — async tests don't need `@pytest.mark.asyncio`. No network in unit tests.
- SQL init scripts are numbered (`01_`, `02_`, ...) and idempotent (use `IF NOT EXISTS`).
- Docker Compose changes are reviewed for volume/hostname/healthcheck correctness.

## Deliberately not used

`requests`, `poetry`, `pip-tools`, `conda`/`mamba`, `flake8`/`isort`/`black`. Don't reintroduce them.

## `.claude/` knowledge index

When deeper context is needed, load from `.claude/knowledge/`:

- `project-skill.md` — master rules (loaded first).
- `architecture.md` — Docker Compose topology and data flow.
- `coding-standards.md` — naming, typing, errors, async, SQL conventions.
- `commands.md` — full command reference.
- `stack-decisions.md` — why each tool was chosen, and what was rejected.

`.claude/playbooks/` contains step-by-step workflows (feature-development, bugfix, code-review, dependency-upgrade, release-checklist). `.claude/agents/` defines specialist subagent personas available in this repo.
