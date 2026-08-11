---
name: alembic-migration
description: The procedure for changing the relational schema in this repo — adding or altering a table or column in backend/app/models.py, generating an Alembic revision, and verifying it. Use whenever a change touches models.py, backend/alembic/versions/, or db_init.py, or when a feature needs a new column.
---

# Changing the schema

`models.py` is the source of truth. Alembic revisions are how a change reaches an existing
database. The server migrates to head on boot, so a missing revision means the feature works on
your machine and breaks on every machine that already has data. See I-23.

## The footgun, first

`alembic revision --autogenerate` compares `models.py` against **whatever database you point it
at**. Pointed at a long-lived development database, it does not emit your one new column. It
emits `drop_table()` for real user tables — orphans left behind by removed features that
`models.py` no longer declares — plus roughly 126 spurious TEXT-vs-VARCHAR type changes from the
legacy pre-Alembic `ALTER`s. Applied, that migration deletes user data.

`make db-revision` exists to close this. It builds a throwaway database from the migrations in a
`mktemp -d`, autogenerates against that, and deletes it. The diff is then migrations-vs-models,
which is the diff you actually want.

**Never run `alembic revision` directly. Always `make db-revision m="..."`.**

## Procedure

1. **Edit `backend/app/models.py`.** New columns must be nullable, or carry a server default.
   An existing row cannot satisfy a `NOT NULL` column that has no default, and the migration
   fails on exactly the databases that matter — the ones with data in them.

2. **Generate:** `make db-revision m="add foo to bar"`

3. **Read the generated file** in `backend/alembic/versions/`. This step is not optional, and it
   is the reason this skill exists. Check:
   - No `drop_table()` or `drop_column()` you did not intend. If one appears, the diff was taken
     against the wrong database — stop and re-read the target, do not "fix" the file by hand.
   - No type churn on columns you never touched.
   - `down_revision` points at the current head. Two branches both adding a revision produce two
     heads and the next boot fails.
   - The upgrade actually contains your change.

4. **Guard additive columns.** Every additive revision needs a column guard — check for the
   column's existence before adding it. Databases in the wild have been through the frozen
   `db_init.py` bridge and may already have it, and an unguarded `ADD COLUMN` aborts boot.

5. **Apply:** `make db-migrate` (or restart the server, which migrates on boot).

6. **Verify:** `cd backend && uv run pytest tests/test_schema_drift.py`. This is the test that
   fails CI when `models.py` and the migrations disagree — it is the gate for this whole
   procedure. Then `make ci`.

## Do not

- **Do not add to `db_init.py`.** `create_all_tables()` is a frozen one-time bridge that lifts
  pre-Alembic databases to the baseline. It is not where schema changes go, and adding to it
  splits the source of truth in two.
- **Do not hand-edit an applied revision.** Write a new one.
- **Do not touch the FTS5 virtual tables here.** They are raw SQL in `db_init.py` and Alembic is
  configured to ignore them by name. Their column order is a positional contract (`c0`, `c1`,
  `c2`) that SQLite will silently misread rather than error on — see I-4.
