# Anti-Patterns

Things to **avoid** in this repo. Each entry: the bad pattern → why → the right way.

---

## `requests` in async code

- **Bad**: `import requests; r = requests.get(url)` inside an `async def`.
- **Why**: blocks the event loop; degrades throughput.
- **Right**: `async with httpx.AsyncClient(timeout=...) as c: r = await c.get(url)`.

---

## Mocking data structures in tests

- **Bad**: `mock.patch("pandas.DataFrame")` or `mock.MagicMock(spec=MyModel)`.
- **Why**: tests pass while production breaks on real shape, dtype, or validation issues.
- **Right**: use real objects with minimal valid data.

---

## Hidden global config inside modules

- **Bad**: `from config import SETTINGS; SETTINGS["key"] = "value"`.
- **Why**: action-at-a-distance; hides dependencies; breaks tests.
- **Right**: load settings once at startup, pass down explicitly or inject.

---

## Bare `except:` and `except Exception: pass`

- **Bad**: `try: x() except: pass`.
- **Why**: hides bugs, hides keyboard interrupt, makes debugging impossible.
- **Right**: catch the narrowest type, log + re-raise or convert to a domain exception.

---

## `print` in library code

- **Bad**: `print(f"got {n} rows")` left in committed code.
- **Why**: bypasses log levels, no structure, can't be filtered or routed.
- **Right**: `logger = logging.getLogger(__name__); logger.info("got %d rows", n)`.

---

## Hard-coded paths

- **Bad**: `df = pd.read_parquet("/Users/alice/data/file.parquet")`.
- **Why**: breaks on every other machine and in CI.
- **Right**: paths come from `Settings()` (env var with a project-relative default).

---

## Optimizing without a benchmark

- **Bad**: rewriting code for "speed" because it "looks slow".
- **Why**: spends time, increases complexity, often achieves nothing or regresses.
- **Right**: profile first; capture before/after numbers; commit the benchmark.

---

## Refactor + feature in one PR

- **Bad**: rename + restructure + add new table, all in one commit.
- **Why**: review becomes impossible; rollback is all-or-nothing.
- **Right**: refactor PR (no behavior change), then feature PR.

---

## No type annotations on public functions

- **Bad**: `def process(data): ...`.
- **Why**: no IDE support, no mypy checking, ambiguous contract.
- **Right**: `def process(data: list[Item]) -> list[Result]: ...`.

---

## Returning bare `dict` from public functions

- **Bad**: `def get_config() -> dict: return {"key": "val"}`.
- **Why**: no schema validation, easy to drift between versions, no IDE autocomplete.
- **Right**: return a typed model (Pydantic, dataclass, TypedDict).

---

## Non-idempotent init scripts

- **Bad**: `CREATE DATABASE db_csm_set;` without `IF NOT EXISTS` check.
- **Why**: Docker runs init scripts only on first container start. If the script is re-run (e.g., after `docker compose down -v`), it fails on the second execution. Also fails if the database was already created by a prior script.
- **Right**: `CREATE DATABASE IF NOT EXISTS db_csm_set;` (or equivalent guard). Every `CREATE`, `ALTER`, and `INSERT` in init scripts must tolerate being run more than once.

---

## Committing `.env` or credentials

- **Bad**: `.env` file staged and committed with real `POSTGRES_PASSWORD`.
- **Why**: secrets in git history are effectively permanent. Every clone exposes them.
- **Right**: `.env` in `.gitignore`. `.env.example` provides the template with placeholder values. Use `docker compose` env-var substitution (`${POSTGRES_PASSWORD}`).

---

## Installing databases on the host

- **Bad**: `brew install postgresql mongodb` and running them as host services.
- **Why**: version drift between developers; manual setup steps; no reproducible environment.
- **Right**: `docker compose up -d` provisions both databases with pinned image versions and init scripts. One command, identical on every machine.

---

## Schema change without consumer coordination

- **Bad**: dropping a column from `equity_curve` without notifying the CSM-SET strategy service that writes to it.
- **Why**: downstream services break on the next write.
- **Right**: document the change in the commit body; coordinate with consumers; prefer additive changes (new columns with `DEFAULT`) over destructive ones.

---

## Forgetting to re-create the network

- **Bad**: `docker compose up -d` fails with "network quant-network not found" and the developer doesn't know why.
- **Why**: `quant-network` is an external network created once per host; if Docker Desktop is reset or the network is pruned, the stack silently fails.
- **Right**: `docker network create quant-network` (documented in README.md as the one-time setup step).

---

> **Append new anti-patterns as you discover them. Pattern → Why → Right way.**
