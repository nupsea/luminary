# Refactor (branch: feat/refac-1-luminary)

All planned audits (#1–#15) complete as of 2026-05-15. Full history in `git log` (search `refactor:` / `chore:` since branch root).

## Intentional holdouts

- `components/reader/DocumentReader.tsx` (~1,290 lines) and `components/NoteReaderSheet.tsx` (~1,039 lines) stay as tightly-coupled orchestrators (design principle 6). Revisit only if orchestration shape genuinely changes.
- `services/summarizer.py` (696 lines) not split — document vs. library summarization are too coupled to separate cleanly without a real pain trigger.
- CI grep for new `session.execute(` in routers: not yet wired.

## Design principles

1. **Re-export, don't break.** When code moves, keep the old name importable from its original home (`# noqa: F401`).
2. **Re-exports are name bindings, not call sites.** After a move, update `mock.patch("old.X")` → `mock.patch("new.X")` or the patch silently no-ops.
3. **Indirect through the original module for swappable singletons.** `get_llm_service`, `get_retriever`, `get_graph_service` etc. should be reached via `from app.services import X as _X_module` and called as `_X_module.get_Y()` at call time — never `from app.services.X import get_Y` (that binds the symbol locally and silently breaks patching).
4. **Schemas + helpers + body, in that order.** God-router playbook: (a) lift Pydantic schemas to `app/schemas/<entity>.py`; (b) lift pure helpers to `app/services/<entity>_service.py`; (c) only then split the body.
5. **Repos own session ops, services own logic, routers own HTTP.** When a router keeps `session.execute` after a repo lands, document why (transactional, bespoke join shape, etc.).
6. **Don't fight tightly-coupled orchestrators.** Helpers that flush mid-transaction and fan out across stores stay where they are with a comment explaining why.
7. **Measure before and after.** Every phase commit records line counts. Makes regressions visible.
8. **Audit `# noqa: PLC0415` after each extraction.** Lazy imports were circular-dep workarounds; promote and delete the noqa when the cycle is broken.
9. **When you build a facade, pass-through with kwargs.** Prefer `return self._repo.method(**kwargs)` so any signature drift surfaces as a TypeError at test time, not as silent data corruption.

## Pre-existing test failures (do not chase unless asked)

- Frontend vitest: 11 failures in `pdfHighlightOverlay.test.ts` and `pdfTocUtils.test.ts`.
- Backend pytest: `test_pomodoro_service::test_stats_only_completed_count_total` is date-flaky.
- Frontend tsc: `evals/AblationsTab.tsx` (recharts type) and `pages/Admin.tsx` (unused `Legend` import).
