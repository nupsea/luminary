"""Shutdown drains every fire-and-forget registry, not a list kept by hand.

Ten modules held their own `_background_tasks` set and `lifespan` named two of
them, so note, flashcard and tag work ran on against a closing database exactly
the way the ingestion nodes' work did before their set was added by hand. The
remedy is that a registry declares itself through `background.task_registry`,
which is what makes it visible to shutdown -- so the structural test below is the
load-bearing one: it fails the moment someone writes `set()` again, which is the
only way this can regress.

`test_a_registry_shutdown_cannot_see_is_not_drained` is the discriminator. Without
it the first test would pass against a task that some other part of shutdown
happened to cancel.
"""

import ast
import asyncio
import pathlib

import pytest

from app.main import app, lifespan
from app.services import background

APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "app"


def _bare_registry_declarations() -> list[str]:
    """Modules assigning a `_background_tasks` set literal instead of registering."""
    found = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets = (
                [node.target] if isinstance(node, ast.AnnAssign) else getattr(node, "targets", [])
            )
            if not any(isinstance(t, ast.Name) and t.id == "_background_tasks" for t in targets):
                continue
            value = node.value
            is_set_call = (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "set"
            )
            if is_set_call or isinstance(value, ast.SetComp):
                found.append(f"{path.relative_to(APP_ROOT.parent)}:{node.lineno}")
    return found


def test_no_module_declares_a_registry_shutdown_cannot_find():
    bare = _bare_registry_declarations()
    assert not bare, (
        "these modules hold a fire-and-forget registry that lifespan shutdown will "
        f"never drain: {bare}. Use `task_registry(__name__)` from "
        "app.services.background instead of `set()`."
    )


@pytest.fixture
def scratch_registry():
    """A registry belonging to no real module, removed again afterwards."""
    name = "tests.scratch_background_registry"
    registry = background.task_registry(name)
    yield registry
    background._REGISTRIES.pop(name, None)


async def _task_left_running_across_lifespan(registry) -> asyncio.Task:
    """Start a never-finishing task inside the app's lifespan, then leave it.

    The lifespan is driven directly rather than through `TestClient`, because a
    `TestClient` exit also closes the loop, and `asyncio.Runner.close()` cancels
    every remaining task on the way out -- which would make an undrained registry
    indistinguishable from a drained one. What matters is that the task is
    cancelled *during* shutdown, while the stores are still open; that is the
    difference between orderly cancellation and work running on against a closing
    database.
    """
    task: asyncio.Task | None = None
    async with lifespan(app):
        task = asyncio.create_task(asyncio.sleep(3600))
        if registry is not None:
            registry.add(task)
        await asyncio.sleep(0)
    assert task is not None
    await asyncio.sleep(0)
    return task


async def test_shutdown_drains_a_registry_it_was_never_told_about(scratch_registry):
    task = await _task_left_running_across_lifespan(scratch_registry)

    assert task.cancelled(), (
        "a task in a registered registry survived shutdown; background work is "
        "running on against a database that is closing"
    )


async def test_a_registry_shutdown_cannot_see_is_not_drained():
    """The check firing: an untracked task is exactly what used to survive."""
    task = await _task_left_running_across_lifespan(None)

    assert not task.cancelled(), (
        "an untracked task was cancelled anyway, so the test above proves nothing "
        "about the registry being drained"
    )
    task.cancel()
