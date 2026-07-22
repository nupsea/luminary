## Description

Include a clear summary of the changes and specify which issue is fixed. Mention any new dependencies introduced.

Fixes # (issue number)

---

## Type of Change

Please check the options that apply:

- [ ] **Bug Fix** (non-breaking change which fixes an issue)
- [ ] **New Feature** (non-breaking change which adds functionality)
- [ ] **Breaking Change** (fix or feature that would cause existing functionality to behave differently)
- [ ] **Documentation Update** (improvements to docs, evals, or comments)
- [ ] **Refactoring / Maintenance** (code cleanup, performance optimizations, no API/schema changes)

---

## Key Verification Steps

Describe the tests or steps you ran to verify your changes. If this is a UI change, please include **screenshots** or a **GIF** showing the before/after behavior.

### 🧪 Local Tests Run
- [ ] **Backend Tests**: Run `make test` and ensure all tests pass.
- [ ] **Linting & Formatting Check**: Run `make lint` (runs `ruff` and checks schema coverage).
- [ ] **Frontend Build & Types**: Run `make build` and verify `cd frontend && npx tsc --noEmit` passes.
- [ ] **Full Integration Suite**: Run `make ci` (runs all checks together).

### 🗄️ Database Changes (If applicable)
*If you modified `backend/app/models.py`:*
- [ ] I ran `make db-revision m="description"` to generate the migration file.
- [ ] I inspected the generated revision under `backend/alembic/versions/` to verify it matches my intention (no destructive auto-drops).
- [ ] I applied the migration locally using `make db-migrate` and verified it runs.

---

## Contributor Checklist

- [ ] My code follows the code style guidelines of this project (runs `ruff` locally).
- [ ] I have performed a self-review of my own code.
- [ ] I have commented my code, particularly in hard-to-understand areas (e.g., FTS5 column contracts, Alembic overrides).
- [ ] My changes generate no new warnings during the build or test runs.
- [ ] I have added tests that cover my changes (unit tests, integration tests, or evaluation harness cases).
- [ ] I have updated the documentation (or inline comments) to reflect my changes.
