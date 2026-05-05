# Claude Agents

Specialized sub-agents for this project. Reference an agent in your prompt to invoke its expertise.

## Available Agents

### Architecture & Schema Design

| Agent | Purpose |
|---|---|
| [`@python-architect`](python-architect.md) | Module boundaries, async patterns, type safety, Docker Compose topology |
| [`@refactor-specialist`](refactor-specialist.md) | Behavior-preserving structural change under green tests |
| [`@api-designer`](api-designer.md) | SQL DDL schema design, MongoDB collection contracts, data model review |

### Engineering Workflow

| Agent | Purpose |
|---|---|
| [`@dependency-manager`](dependency-manager.md) | uv package management, dependency updates, environment setup |
| [`@git-commit-reviewer`](git-commit-reviewer.md) | Pre-commit validation, commit message standards, repo hygiene |
| [`@documentation-specialist`](documentation-specialist.md) | Docstrings, README, CHANGELOG, init-script comments, roadmap docs |
| [`@release-manager`](release-manager.md) | Version bumps, CHANGELOG, tagging, publish, smoke test |

### Reliability

| Agent | Purpose |
|---|---|
| [`@bug-investigator`](bug-investigator.md) | Root-cause analysis, repro-first fixes, regression tests |
| [`@test-engineer`](test-engineer.md) | pytest specialist — unit, integration, DB connectivity, regression tests |
| [`@performance-optimizer`](performance-optimizer.md) | Profiling, query performance, index tuning, Docker resource usage |
| [`@security-reviewer`](security-reviewer.md) | Secrets, injection, auth, validation, dep CVEs, Docker security |

## Usage

Reference an agent in your prompt to invoke its expertise:

```
@python-architect review this new init-script for schema correctness
@api-designer review the equity_curve table for data-model fit
@dependency-manager add pymongo to the project dependencies
@git-commit-reviewer prepare a commit for the schema changes
@documentation-specialist add comments to init-scripts/03_schema_csm_set.sql
@bug-investigator why does the MongoDB connection test fail?
@test-engineer add DB connectivity smoke tests
@performance-optimizer review the query plan for daily_performance aggregation
@security-reviewer check docker-compose.yml for exposed secrets
@refactor-specialist split init-scripts/03_schema_csm_set.sql into smaller files
```

## Roadmap Context

The project is in early bootstrap (Phase 1 of 4). See `docs/plans/ROADMAP.md` for the full plan:
- **Phase 1**: Docker Compose + network bootstrap
- **Phase 2**: PostgreSQL + TimescaleDB schema
- **Phase 3**: MongoDB collections + Python connectivity
- **Phase 4**: Health checks + backup + docs

When working on DB-infra tasks, orient agents toward init-scripts, `docker-compose.yml`, `scripts/backup.sh`, and `README.md` rather than Python application code.

## Related

- [Project Skill](../knowledge/project-skill.md) — master rules file
- [Coding Standards](../knowledge/coding-standards.md) — enforceable conventions
- [Architecture](../knowledge/architecture.md) — stack topology and data flow
- [Roadmap](../../docs/plans/ROADMAP.md) — master roadmap (4 phases)
- [Playbooks](../playbooks/) — step-by-step workflows
