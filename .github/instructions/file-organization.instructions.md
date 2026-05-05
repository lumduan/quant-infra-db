---
applyTo: '**'
---
## File Organization — Strict Rules

### Directory Structure Requirements:

- `docker-compose.yml`: Core services definition (PostgreSQL + MongoDB). Single source of truth for the DB stack.
- `init-scripts/`: SQL and JS scripts that Docker runs on first container start. Numbered `01_` through `0N_` for ordering. Idempotent.
- `scripts/`: Utility scripts (`backup.sh`, connectivity smoke tests).
- `src/`: Core library — importable Python package.
- `tests/`: ALL pytest tests, comprehensive coverage required (≥80%).
- `docs/`: ALL documentation and design docs. Includes `docs/plans/ROADMAP.md`.
- `.claude/`: AI agent context, knowledge, playbooks, and templates.
- `.github/`: CI/CD workflows, issue/PR templates, AI instructions.
- `.env.example`: Credential template. `.env` itself is gitignored.

### File Naming Conventions:

- `snake_case` for all Python files.
- `kebab-case` for Docker Compose services and container names.
- SQL init scripts: `0N_descriptive_name.sql` (numbered, `snake_case` name).
- MongoDB init scripts: `mongo-init.js` (or `0N_descriptive_name.js` if multiple).
- Test files MUST match pattern `test_*.py`.
- Clear, descriptive names indicating purpose.

### Module Organization:

- One class/concern per module where practical.
- Group related modules in packages with `__init__.py`.
- Keep files under ~500 lines for `.py`, ~80 lines for SQL init scripts; split when exceeded.
- Mirror the source structure in the tests directory.

### File Deletion:

- Use `rm <path>` to delete files from the filesystem.
- Always confirm file removal before executing.
- Verify no remaining imports or Docker references point to the deleted file.
- For init scripts: renumber remaining scripts if a numbered script is removed.
