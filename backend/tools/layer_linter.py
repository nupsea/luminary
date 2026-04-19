"""Layer linter: enforces forward-only dependency flow in the Luminary backend.

LAYER_ORDER defines numeric levels. A lower-layer module (lower number) must not import
from a higher-layer module (higher number). Dependency flow: Types → Config → Repo →
Service → Workflow → Router → Main.

Run: uv run python tools/layer_linter.py
Exit 0: no violations. Exit 1: violations found.
"""

import ast
import sys
from pathlib import Path

LAYER_ORDER: dict[str, int] = {
    "types": 0,
    "config": 1,
    "database": 1,
    "models": 1,
    "repo": 2,
    "service": 3,
    "workflow": 3,
    "router": 4,
    "main": 5,
}

# Map subdirectory names to layer keys
SUBDIR_MAP: dict[str, str] = {
    "services": "service",
    "routers": "router",
    "workflows": "workflow",
}

APP_DIR = Path(__file__).parent.parent / "app"


def get_layer(relative_path: Path) -> int | None:
    """Return the layer number for a file relative to APP_DIR, or None if unclassified."""
    parts = relative_path.parts
    if len(parts) == 1:
        # Root-level file: use the stem name
        stem = parts[0].removesuffix(".py")
        return LAYER_ORDER.get(stem)
    else:
        # Subdirectory file: use the first directory component
        dirname = parts[0]
        key = SUBDIR_MAP.get(dirname, dirname)
        return LAYER_ORDER.get(key)


def get_layer_for_module(module: str) -> int | None:
    """Get layer number for an 'app.*' module string.

    e.g. 'app.services.qa' -> 3, 'app.config' -> 1, 'app.telemetry' -> None
    """
    if not module.startswith("app."):
        return None
    inner = module[len("app.") :]
    # Inner might be 'services.qa' or 'config' or 'types'
    first_segment = inner.split(".")[0]
    key = SUBDIR_MAP.get(first_segment, first_segment)
    return LAYER_ORDER.get(key)


def check_file(filepath: Path) -> list[str]:
    """Return violation messages for a single file."""
    relative = filepath.relative_to(APP_DIR)
    source_layer = get_layer(relative)
    if source_layer is None:
        return []  # unclassified (e.g. telemetry.py, db_init.py) — skip

    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return []

    violations = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)

        for module in modules:
            target_layer = get_layer_for_module(module)
            if target_layer is not None and source_layer < target_layer:
                violations.append(
                    f"Layer violation in app/{relative}: "
                    f"layer {source_layer} cannot import from layer {target_layer} "
                    f"({module}). "
                    f"Remediation: move shared logic to a types or service module, "
                    f"or restructure so higher layers depend on lower layers only."
                )

    return violations


def main() -> int:
    py_files = sorted(APP_DIR.rglob("*.py"))
    all_violations: list[str] = []
    for filepath in py_files:
        if "__pycache__" in filepath.parts:
            continue
        all_violations.extend(check_file(filepath))

    if all_violations:
        for v in all_violations:
            print(f"ERROR: {v}", file=sys.stderr)
        print(
            f"\nlayer_linter: {len(all_violations)} violation(s) found. Fix before committing.",
            file=sys.stderr,
        )
        return 1

    print("layer_linter: all layer boundaries respected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
