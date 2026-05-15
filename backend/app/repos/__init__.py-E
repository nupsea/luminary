"""Per-entity repository layer.

Repos own all `session.execute / add / commit / delete` calls for a
single SQLAlchemy entity. Routers depend on a repo instance via
`Depends(get_X_repo)`; services that need raw DB access still hold an
`AsyncSession` directly.

Audit #9 in `docs/refactor-progress.md` tracks the migration. Each repo
is added incrementally as the corresponding router is migrated.
"""
