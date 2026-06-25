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
  │     ├── db_csm_set       — equity_curve, trade_history, backtest_log
  │     ├── db_gateway       — daily_performance, portfolio_snapshot
  │     ├── db_market_data   — market_data.{ohlcv, corporate_actions,
  │     │                      universe_membership, ohlcv_adjusted view} + CAGGs
  │     ├── db_execution     — execution.{orders, fills, order_events}
  │     │                      + frozen-state-machine triggers
  │     ├── db_orderbook     — orderbook.{raw_events, trades, book_snapshots,
  │     │                      settlements, gap_windows, dq_manifests, greeks}
  │     └── db_ticker        — ticker.trades (T&S, source-tagged: Liberator + Streaming Pro)
  └── quant-mongo    (mongo:latest)
        └── csm_logs — backtest_results, model_params, signal_snapshots
```

`db_market_data` is the shared canonical OHLCV store for the Market Data engine
(`feature-market-data-engine`, Phase 1). It is a **dedicated database** (not a `db_gateway`
schema) so the store is independently owned (ADR D4/D7). The `market_data.ohlcv` hypertable
keys on `(symbol, timeframe, ts)` (Option A multi-timeframe); prices are `numeric(18,6)`,
volume/open_interest `numeric(20,4)`; raw bars are stored and adjusted on read via the
`ohlcv_adjusted` view. The standalone `quant-marketdata-engine` becomes the sole writer in
Phase 2; init scripts `10_schema_market_data.sql` + `11_market_data_caggs.sql`.

`db_execution` is the durable order store for the Execution engine
(`feature-execution-engine`, Phase 1). **Plain tables, not hypertables** (low-volume
real-money command plane; FK targets cannot be hypertables): `execution.orders` (PK =
idempotency key `client_order_id`), `execution.fills` (fill dedupe on
`(client_order_id, broker_fill_id)`), and append-only `execution.order_events`. DB triggers
enforce exactly the frozen 9-state order machine (13 legal edges, terminal states
immutable) and auto-append one audit row per transition. The standalone
`quant-execution-engine` becomes the sole writer in Phase 2; init script
`12_schema_execution.sql`.

`db_orderbook` is the durable hot-tier store for the Order-Book Capture engine
(`feature-orderbook-engine`, Phase 1; market-data plane, host `:8600`). It is a **dedicated
database** (mirroring `db_market_data` / `db_execution`) holding the `orderbook` schema:
**TimescaleDB hypertables** for the high-volume event streams (`orderbook.raw_events`
append-only, `orderbook.trades`, derived `orderbook.book_snapshots`) plus **plain** reference
tables (`orderbook.settlements`, `orderbook.gap_windows`, `orderbook.dq_manifests`) plus the
derived EOD greeks table (`orderbook.greeks` — Black-76 IV/greeks for TFEX SET50 options, one
row per (date, option-symbol), freely regenerable; `init-scripts/15_orderbook_greeks.sql`).
Prices are `numeric(18,6)`, volume `bigint`, capture clocks `bigint` nanoseconds. The
append-only binary raw log (NVMe) + Parquet cold tier are the systems of record; this DB is the
regenerable queryable mirror. Compression + a **provisional** (Stage-B-calibration-deferred)
retention policy sit on the hypertables. The standalone `quant-orderbook-engine` becomes the
sole writer; init script `14_schema_orderbook.sql`.

`db_ticker` is the durable hot-tier time & sales (T&S) store for the Ticker engine
(`feature-ticker-engine`, Phase 1 — "the tick plane"; market-data plane, host `:8800`). It is a
**dedicated database** (mirroring `db_orderbook`) holding the `ticker` schema: a single
**TimescaleDB hypertable** `ticker.trades` (the high-volume trade stream). Trades come from
**two independent upstreams, never `vs`-unioned** (ADR TK2) — the Liberator `TickerV2` feed and
the Streaming Pro bridge (svc-3) — distinguished by the `source` column (`liberator` carries the
venue `vs`; `streaming_pro` carries the per-frame `seq`). Prices are `numeric(18,6)`, volume
`bigint`. The append-only binary raw logs are the systems of record; this DB is the regenerable
queryable mirror (SELECT, INSERT only — no UPDATE/DELETE). The standalone `quant-ticker-engine`
is the sole writer; init script `17_schema_ticker.sql`.

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
