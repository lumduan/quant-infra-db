# Coding Standards

Concrete, enforceable rules. If you can't comply, document why in code with a comment.

## Naming

- **Modules / functions / variables**: `snake_case`.
- **Classes / Pydantic models / TypedDicts**: `PascalCase`.
- **Constants / sentinels**: `SCREAMING_SNAKE_CASE`.
- **Private**: `_leading_underscore` for module-private.
- **Avoid abbreviations** except well-established domain terms.
- **SQL tables / columns**: `snake_case`. Table names are plural where they represent collections (`equity_curve`, not `equity_curves` is also fine — be consistent).
- **MongoDB collections**: `snake_case`; database names use `snake_case`.

## Typing

- Full type annotations on every function — args and return.
- No bare `Any`. If unavoidable, justify in a comment.
- Prefer `Sequence`, `Mapping`, `Iterable` for parameters; `list`, `dict` for returns when concrete.
- Use `Optional[X]` only when `None` is meaningful.
- Pydantic models for all data crossing module / process boundaries.

## File Size & Complexity

- Target ≤ 500 lines per `.py` file.
- Functions ≤ ~50 lines unless cohesion demands more.
- SQL init scripts ≤ ~80 lines each. Split by concern (database creation, extension enablement, schema per logical database).
- Split files when they exceed the budget; group related modules in packages.

## Errors

- Define module-local exceptions in each subpackage's `errors.py`.
- Inherit from a single root exception class.
- Never `raise Exception(...)`; never `except Exception: pass`.
- Catch the narrowest type that captures the failure mode.

## Imports

- ruff-isort sorted: stdlib → third-party → local, blank line between groups.
- No relative imports beyond one level (`from . import x`, never `from ...util import y`).
- No wildcard imports (`from x import *`).

## Logging

- `logger = logging.getLogger(__name__)` at module top.
- Never `print` in library code.
- Use `%` formatting for deferred interpolation: `logger.info("processed %d items", n)` — not f-strings.
- Never log secrets, tokens, or full request bodies.

## Async

- Every public function performing I/O is `async def`.
- Use `httpx.AsyncClient` (not `requests`) for HTTP.
- Use `asyncio.gather` for independent awaitables.
- Always set `timeout=` on HTTP calls.
- Use `async with` for resource management.

## SQL / init-scripts

- Scripts are numbered (`01_`, `02_`, ...) and run alphabetically by Docker on first container start.
- Every SQL object uses `IF NOT EXISTS` (`CREATE TABLE IF NOT EXISTS`, `CREATE EXTENSION IF NOT EXISTS`). Init scripts must be idempotent.
- Use `TIMESTAMPTZ` (not `TIMESTAMP`) for all time columns — UTC is the only time zone stored.
- TimescaleDB hypertables: call `SELECT create_hypertable(...)` immediately after `CREATE TABLE`.
- Always add indexes on columns used in `WHERE` / `JOIN` / `ORDER BY` clauses, especially `(strategy_id, time DESC)`.
- MongoDB init scripts: use `db.getSiblingDB(...)` to target the correct database. Create indexes immediately after collections.

## Docker Compose

- Service definitions declare `container_name`, `restart: always`, environment variables from `.env`, and named volumes.
- Every service has a `healthcheck` block (pg_isready for PostgreSQL, mongosh ping for MongoDB).
- Network is external (`quant-network`), created once per host.
- Ports are exposed only for local development; in production, services on the shared network use internal hostnames.

## Docstrings

Google style, mandatory on public functions:

```python
async def process_items(
    items: list[Item],
    *,
    batch_size: int = 100,
) -> list[Result]:
    """Process items in batches.

    Args:
        items: Input items to process. Must not be empty.
        batch_size: Number of items per batch. Defaults to 100.

    Returns:
        Processed results in the same order as input.

    Raises:
        ValueError: If `items` is empty.

    Example:
        >>> results = await process_items(items, batch_size=50)
    """
```

## Tests

- One test file per source file, mirroring path.
- `pytest-asyncio` is in `auto` mode (`asyncio_mode = "auto"`) — async tests don't need `@pytest.mark.asyncio`.
- No network in unit tests; integration tests behind markers.
- Real data structures (no mocks of data types).
- DB connectivity tests use the real Docker Compose stack (marked as integration tests).
- See [Test Engineer](../agents/test-engineer.md).
