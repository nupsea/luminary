"""I-2: sync Kuzu/LanceDB calls must not run on the event loop.

The server runs a single worker, so one unwrapped traversal stalls every
concurrent request -- a 2ms /tags/graph measured 8.5s behind an all-library
/graph. Wrap them in asyncio.to_thread.
"""

import ast
from pathlib import Path

APP = Path(__file__).parent.parent / "app"

STORE_HINTS = ("graph", "kuzu", "lance", "vector_store")

# Factories and non-I/O helpers whose names happen to match STORE_HINTS.
NOT_IO = {
    "get_graph_service",
    "get_lancedb_service",
    "get_note_graph_service",
    "format",
    "extend",
    "append",
    "add_done_callback",
    "ainvoke",
    "join",
    "lower",
    "strip",
    "get",
}

# Pre-existing debt. May only shrink. See docs/refactor-quality-plan.md (WP6).
BASELINE = 44


def _sync_store_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        deferred: set[int] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Await):
                deferred.add(id(node.value))
            if isinstance(node, ast.Call):
                callee = getattr(node.func, "attr", "") or getattr(node.func, "id", "")
                # to_thread(fn, ...) and create_task(coro) both move work off the loop.
                if callee in ("to_thread", "create_task", "run_in_executor"):
                    for arg in node.args:
                        deferred.add(id(arg))
                        deferred.add(id(getattr(arg, "func", arg)))
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call) or id(node) in deferred:
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or id(func) in deferred:
                continue
            if func.attr in NOT_IO:
                continue
            rendered = ast.unparse(func)
            if any(hint in rendered.lower() for hint in STORE_HINTS):
                out.append(f"{path.relative_to(APP.parent)}:{node.lineno} {rendered}")
    return out


def test_sync_store_calls_do_not_grow() -> None:
    violations: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in path.parts or "scripts" in path.parts:
            continue
        violations.extend(_sync_store_calls(path))

    assert len(violations) <= BASELINE, (
        f"New sync store calls on the event loop ({len(violations)} > {BASELINE}). "
        "Wrap in asyncio.to_thread per I-2:\n" + "\n".join(f"  - {v}" for v in sorted(violations))
    )
    assert len(violations) == BASELINE, (
        f"Sync store calls dropped to {len(violations)}; lower BASELINE to match."
    )
