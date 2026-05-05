# Feature Development Playbook

Repeatable step-by-step workflow for adding new features.

## 1. Read context

- Read `project-skill.md` in `.claude/knowledge/`.
- Read `docs/plans/ROADMAP.md` to confirm the feature aligns with the current phase.
- Read related source files (init scripts, `docker-compose.yml`, Python modules) to understand existing patterns.
- Check `CHANGELOG.md` for recent changes that may conflict.

## 2. Design

- Sketch the implementation approach in plain text.
- Identify which files change and in what order.
- For schema/init-script changes: document the impact on downstream consumers.
- For Docker Compose changes: note any new volumes, networks, or environment variables.
- For non-trivial features, write a brief plan before coding.

## 3. Test first

- Write a failing test that defines the expected behavior.
- DB features: write a smoke test that connects to the running stack and verifies the new schema/collection.
- Keep tests small: one assert per test where practical.

## 4. Implement

- Write the minimum code to make the test pass.
- Follow the Hard Rules in `project-skill.md`.
- Init scripts: numbered, idempotent, ordered by dependency.
- Docker Compose: verify `docker compose up -d` works before committing.

## 5. Quality gate

All four must pass:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
```

For DB-infra changes, also verify:
```bash
docker compose up -d
docker compose ps   # both services healthy
```

Fix every issue before moving on.

## 6. Document

- Add an `## [Unreleased]` entry to `CHANGELOG.md`.
- Update `README.md` if connection strings or setup steps changed.
- Add or update docstrings on new public APIs.
- If the feature completes a roadmap task, mark it `[x]` in `docs/plans/ROADMAP.md`.

## 7. Commit

Use a [Conventional Commits](https://www.conventionalcommits.org/) message:

```
feat: add <feature description>
```

Use `infra` scope for Docker/database changes:
```
infra: add <description>
```

Include `Co-Authored-By: Claude Code <noreply@anthropic.com>` if an AI agent wrote the change.

## 8. Verify

```bash
# Docker Compose stack
docker compose up -d && docker compose ps

# Python app (if applicable)
docker build -t quant-infra-db:dev .
docker run --rm quant-infra-db:dev

# Connectivity smoke test
uv run python -c "import psycopg2; print(psycopg2.connect('postgresql://postgres:<pass>@localhost:5432/db_csm_set'))"
```
