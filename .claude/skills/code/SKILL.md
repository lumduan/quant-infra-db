---
name: code
description: Universal coding skill — enforce standards, catch anti-patterns, run quality gate
user-invocable: true
tools: Read, Write, Edit, Bash, Glob, Grep
---

# Universal Coding Skill

When invoked, enforce the following rules on all code you write or review. Load
project-specific details from `.claude/knowledge/` and `CLAUDE.md` as needed.

## Hard Rules (non-negotiable)

1. **Always `uv run`.** Never `python`, `pip`, `poetry`, or `conda` directly.
2. **Async-first I/O.** All HTTP via `httpx.AsyncClient`. `requests` is forbidden
   in library code (sync, blocks the event loop).
3. **Pydantic v2 at boundaries.** Data crossing module/process boundaries goes
   through Pydantic models — never raw dicts.
4. **Full type annotations** on every public function — args and return. No bare
   `Any` without justification in a comment.
5. **>= 80% test coverage.** Enforced in CI. New features must include tests.
6. **No secrets in repo.** All config via env vars (pydantic-settings). `.env` is
   gitignored; `.env.example` provides the template.
7. **Ruff + mypy clean before commit.** Run the full quality gate.
8. **Conventional Commits.** `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`,
   `infra:`.

## Anti-Patterns (auto-flag these)

| Anti-Pattern | Why It's Bad | Right Way |
|---|---|---|
| `import requests` in async code | Blocks event loop | `httpx.AsyncClient` with `timeout=` |
| `except Exception: pass` | Hides bugs, hides KeyboardInterrupt | Catch narrowest type; log + re-raise |
| `print()` in library code | Bypasses log levels, no structure | `logger = logging.getLogger(__name__)` |
| Hard-coded paths | Breaks on every other machine | `Settings()` with env-var overrides |
| Mocking data structures in tests | Tests pass, production breaks | Real objects with minimal valid data |
| Refactor + feature in one PR | Review impossible, rollback all-or-nothing | Separate PRs: refactor first, then feature |
| `dict` return from public functions | No schema, no IDE support | Pydantic model, dataclass, or TypedDict |
| No type annotations on public functions | No mypy, no IDE, ambiguous contract | Full annotations: args and return |
| `Any` in type annotations | Defeats the type checker | Narrow type or justify in comment |
| `from x import *` | Pollutes namespace, hides origin | Explicit imports only |

## Naming & Style

- **snake_case**: modules, functions, variables, SQL tables/columns
- **PascalCase**: classes, Pydantic models, TypedDicts
- **SCREAMING_SNAKE_CASE**: constants, sentinels
- **\_leading_underscore**: module-private
- No abbreviations except well-established domain terms

## Imports

ruff-isort order: stdlib -> third-party -> local, blank line between groups.
No relative imports beyond one level. No wildcard imports.

## Error Handling

- Module-local exceptions in each subpackage's `errors.py`
- All inherit from a single root exception class
- Never `raise Exception(...)`; never bare `except:`
- Catch the narrowest type that captures the failure mode

## Logging

```python
logger = logging.getLogger(__name__)
logger.info("processed %d items", n)  # % formatting, not f-strings
```

Never log secrets, tokens, or full request bodies.

## Docstrings

Google style on all public functions:

```python
def process(items: list[Item], *, batch_size: int = 100) -> list[Result]:
    """Process items in batches.

    Args:
        items: Input items to process. Must not be empty.
        batch_size: Number of items per batch. Defaults to 100.

    Returns:
        Processed results in the same order as input.

    Raises:
        ValueError: If `items` is empty.
    """
```

## Tests

- One test file per source file, mirroring `src/` path under `tests/`
- No network in unit tests; integration tests behind markers
- Real data structures (no mocks of data types)
- pytest-asyncio in `auto` mode — async tests don't need `@pytest.mark.asyncio`

## Quality Gate

All four must pass before commit. Run them after every code change:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest -v
```

For single-test iteration:
```bash
uv run pytest tests/<path>::<test_name> -v
```

## Pre-Push / Pre-PR Gate (mirror GitHub CI)

Before any `git commit` that will be pushed, and ALWAYS before `git push` or
opening a PR, run the full gate that mirrors `.github/workflows/ci.yml` and
`.github/workflows/security.yml`. If any step fails, fix it locally — never
push and let CI fail.

```bash
uv sync --all-groups --frozen \
  && uv run ruff check . \
  && uv run ruff format --check . \
  && uv run mypy src tests \
  && uv run pytest -v \
  && uv run bandit -r src \
  && uv run pip-audit
```

When `pip-audit` reports CVEs in **transitive** deps (idna, urllib3, etc.),
bump them via:

```bash
uv lock --upgrade-package <pkg1> --upgrade-package <pkg2>
uv sync --all-groups --frozen
uv run pip-audit            # confirm clean (exit 0)
```

Then commit the updated `uv.lock` as `chore(deps): bump <pkg> for <CVE-id>`.

Note: `pip-audit` prints `Dependency not found on PyPI ... quant-infra-db` —
that is informational (the project itself is not published). What matters is
the exit code (`0` = pass) and the absence of `Found N known vulnerabilities`.

## Code Review Checklist

When reviewing code (your own or others'):

1. **Tests first** — do tests describe the behavior? Edge cases covered?
2. **Hard rules** — all 8 rules satisfied?
3. **Anti-patterns** — scan the table above; flag every hit
4. **Type annotations** — full annotations on every public function
5. **Error handling** — narrow catches, domain exceptions, no bare `except:`
6. **Logging** — `logging.getLogger(__name__)`, no `print()`
7. **Imports** — stdlib -> third-party -> local, no wildcards
8. **File size** — <= 500 lines per file, functions <= ~50 lines

## Fix Mode

When asked to fix issues:

1. Run the quality gate first to see what fails
2. Fix ruff issues with `uv run ruff check --fix . && uv run ruff format .`
3. Fix mypy errors one file at a time, reading the error output carefully
4. Fix test failures last — they often reveal real bugs
5. Re-run the full gate after all fixes

## Project-Specific Context

- Read `.claude/knowledge/project-skill.md` for project-specific hard rules
- Read `.claude/knowledge/coding-standards.md` for detailed conventions
- Read `.claude/memory/anti-patterns.md` for project-specific anti-patterns
- Read `CLAUDE.md` for the project's toolchain and architecture
