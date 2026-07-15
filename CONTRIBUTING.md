# Contributing to Learning Mate

First off, thank you for considering contributing to Learning Mate! It's people like you that make it a great tool.

## Code of Conduct
By participating in this project, you agree to abide by our code of conduct.

## How Can I Contribute?

### Reporting Bugs
Before creating bug reports, please check the existing issues to see if the problem has already been reported. When you are creating a bug report, please include as many details as possible. Fill out the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md).

### Suggesting Enhancements
If you have an idea for a feature, feel free to open a [feature request](.github/ISSUE_TEMPLATE/feature_request.md).

### Your First Code Contribution
Look for issues labeled `good first issue`. These are selected as good entry points for new contributors.

## Pull Requests

1. Fork the repo and create your branch from `master`.
2. If you've added code that should be tested, add tests.
3. Ensure the test suite passes.
4. Make sure your code lints.
5. Issue that pull request!

## Development Setup

See `README.md` for instructions on setting up the backend and frontend.

### Useful Commands
- `make dev`: Start both backend and frontend.
- `make ci`: Run all CI checks (linting, tests, build).
- `make test`: Run backend tests.
- `make lint`: Run backend and frontend linting/type checking.
- `make db-migrate`: Apply pending database migrations.
- `make db-revision m="..."`: Generate a migration from your model changes.

## Changing the Database Schema

`backend/app/models.py` is the source of truth. Schema changes are versioned with
Alembic; the server applies pending migrations automatically on boot.

1. Edit the model in `backend/app/models.py`.
2. Generate a revision: `make db-revision m="add foo to bar"`.
3. **Read the generated file** in `backend/alembic/versions/` before committing.
   Autogenerate is a first draft, not an oracle — it cannot infer data backfills, and
   it will happily emit a destructive `drop_table`/`drop_column` if it misreads intent.
4. Apply it: `make db-migrate`.
5. Commit the revision alongside the model change.

`make test` fails if `models.py` and the migrations disagree (`tests/test_schema_drift.py`),
so a forgotten revision is caught in CI rather than by a user's database.

Two things worth knowing:

- **Generate revisions with `make db-revision`, not `alembic revision` directly.** The
  target builds a throwaway database from the migrations and diffs against that. Run
  bare against a long-lived dev database, autogenerate picks up orphan tables from
  removed features and TEXT-vs-VARCHAR noise from the legacy `ALTER` list, and proposes
  dropping real user tables.
- **The `ALTER TABLE` list in `db_init.py` is frozen.** It is a one-time bridge that
  lifts pre-Alembic databases to the baseline revision. Do not add to it.

### FTS5 tables

The five FTS5 virtual tables are raw DDL in `db_init.py`, outside `Base.metadata`.
Alembic is configured to ignore them (`alembic_include_name`) — without that filter it
would drop them and the search index with them. Their **column order is a contract**:
SQLite names the shadow-table columns positionally (`c0/c1/c2`) and code queries those
names, so reordering returns wrong rows instead of raising. See invariant I-4 in
`docs/invariants.md`.
