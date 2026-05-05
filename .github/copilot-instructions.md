# AI Agent Context

## Project Overview

`quant-infra-db` is the **database infrastructure layer** for the Quant Trading system. It provisions PostgreSQL + TimescaleDB and MongoDB through Docker Compose on a shared `quant-network`, consumed by downstream strategy services and the API Gateway.

> Master roadmap: `docs/plans/ROADMAP.md`

## Core Purpose

Provide a reproducible, Docker Compose-based database stack (PostgreSQL + TimescaleDB for time-series/relational data; MongoDB for schema-less documents) that every strategy service and the API Gateway connects to by hostname on a shared Docker network.

## Architecture & Tech Stack

### Database Infrastructure

- **Docker Compose**: Single-command reproducible stack (`docker compose up -d`).
- **PostgreSQL 16 + TimescaleDB**: Hypertables for time-series data (`equity_curve`, `daily_performance`, `portfolio_snapshot`). Standard relational tables for trade history and backtest metadata.
- **MongoDB**: Schema-less document store for backtest results, model parameters, and signal snapshots.
- **Shared network `quant-network`**: All containers communicate by hostname, not IP address.

### Python Layer (thin)

- **Python 3.11+**: Modern Python with full type hint support.
- **Pydantic V2**: Data validation and settings management with strict type enforcement.
- **Async/Await**: Non-blocking I/O operations for optimal performance.

### Dependencies & Package Management

- All Python dependencies MUST be managed using [uv](https://github.com/astral-sh/uv).
- Add dependencies with `uv add <package>` or `uv add --dev <package>`.
- Remove dependencies with `uv remove <package>`.
- Lock dependencies with `uv lock`; `uv.lock` is always committed.
- Run Python scripts and modules using `uv run python <script.py>` or `uv run python -m <module>`.
- Do NOT use pip, poetry, or conda for dependency management or Python execution.

### Design Principles

- **Type Safety First**: Every function has complete type annotations.
- **Async by Default**: All I/O operations use async/await.
- **Pydantic at Boundaries**: Data crossing module boundaries uses Pydantic models.
- **Test Coverage ≥ 80%**: Enforced in CI.
- **uv-Only Workflow**: Every command prefixed with `uv run`.
- **Docker Compose for Infra**: Databases are managed via `docker compose`. Never install PostgreSQL or MongoDB directly on the host.
- **Idempotent Init Scripts**: SQL and JS init scripts use `IF NOT EXISTS` and tolerate re-runs.

## Project Structure

```
.
├── docker-compose.yml              # Core services: postgres + mongodb
├── init-scripts/                   # Run automatically on first container start
│   ├── 01_create_databases.sql     # Create db_csm_set, db_gateway
│   ├── 02_enable_timescaledb.sql   # Enable the TimescaleDB extension
│   ├── 03_schema_csm_set.sql       # Tables: equity_curve, trade_history, backtest_log
│   ├── 04_schema_gateway.sql       # Tables: daily_performance, portfolio_snapshot
│   └── mongo-init.js               # MongoDB: create collections + indexes
├── scripts/
│   └── backup.sh                   # Back up PostgreSQL + MongoDB
├── src/                            # Core library — importable Python package
│   └── main.py                     # Entrypoint
├── tests/                          # pytest suite mirroring src/ structure
├── docs/                           # Documentation and design docs
│   └── plans/
│       └── ROADMAP.md              # Master roadmap (4 phases)
├── .claude/                        # AI agent context, playbooks, and knowledge
├── .github/                        # CI/CD workflows, issue/PR templates, AI instructions
├── pyproject.toml                  # Project configuration and dependencies
├── uv.lock                         # Locked dependencies
├── Dockerfile                      # Multi-stage container build (Python app)
└── README.md                       # Project documentation
```

## Environment Configuration

### Required Environment Variables

Copy `.env.example` to `.env` and fill in real values. Never commit `.env`.

```
POSTGRES_PASSWORD=your_strong_password_here
```

## Core Modules

Document your core modules here as the project grows. Each module should have:

- A clear single responsibility.
- Public API with full type annotations and docstrings.
- Corresponding tests in `tests/`.

## Key Conventions

- **Quality gate before every commit**: `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest`
- **Conventional Commits**: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`
- **No secrets in code**: All config via environment variables.
- **No `print` in library code**: Use `logging.getLogger(__name__)`.
- **SQL init scripts are numbered and idempotent**: `01_` through `0N_`, all use `IF NOT EXISTS`.
- **Docker Compose for databases**: `docker compose up -d` brings up the full stack.

## AI Agent Workflow

See `.claude/knowledge/project-skill.md` for the master rules file that AI agents load first.
See `.claude/playbooks/feature-development.md` for the step-by-step development workflow.
See `docs/plans/ROADMAP.md` for the master roadmap and current phase.
