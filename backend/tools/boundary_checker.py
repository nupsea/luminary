"""Boundary checker: validates FastAPI route function parameters use Pydantic BaseModel types.

Scans all router files and main.py. Prints remediation warnings for route function
parameters typed as raw dict or Any (which bypass Pydantic validation).

Run: uv run python tools/boundary_checker.py
Exits 0 always (advisory warnings — does not fail CI).
"""

import ast
import sys
from pathlib import Path

ROUTERS_DIR = Path(__file__).parent.parent / "app" / "routers"
MAIN_FILE = Path(__file__).parent.parent / "app" / "main.py"

ROUTE_DECORATOR_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}

SIMPLE_TYPES = {"str", "int", "float", "bool", "bytes"}


def is_depends_default(node: ast.expr | None) -> bool:
    """Return True if the default value is a Depends(...) call."""
    if node is None:
        return False
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id == "Depends":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "Depends":
            return True
    return False


def is_raw_type(annotation: ast.expr | None) -> bool:
    """Return True if annotation is a raw dict, dict[...], or Any."""
    if annotation is None:
        return False
    if isinstance(annotation, ast.Name):
        return annotation.id in ("Any", "dict")
    if isinstance(annotation, ast.Subscript):
        if isinstance(annotation.value, ast.Name) and annotation.value.id == "dict":
            return True
    return False


def is_route_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check if the function has a route decorator (@app.get, @router.post, etc.)."""
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Call):
            func = decorator.func
            if isinstance(func, ast.Attribute) and func.attr in ROUTE_DECORATOR_METHODS:
                return True
    return False


def build_defaults_map(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, ast.expr | None]:
    """Map argument names to their default values (or None if no default)."""
    result: dict[str, ast.expr | None] = {}
    args = func.args

    # Positional args: defaults align to the last N of args.args
    n_args = len(args.args)
    n_defaults = len(args.defaults)
    for i, arg in enumerate(args.args):
        default_offset = i - (n_args - n_defaults)
        result[arg.arg] = args.defaults[default_offset] if default_offset >= 0 else None

    # Keyword-only args have parallel kw_defaults list (may contain None for no default)
    for i, arg in enumerate(args.kwonlyargs):
        kw_default = args.kw_defaults[i] if i < len(args.kw_defaults) else None
        result[arg.arg] = kw_default

    return result


def check_file(filepath: Path) -> list[str]:
    """Return warning strings for boundary violations in a single file."""
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return []

    warnings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not is_route_function(node):
            continue

        defaults = build_defaults_map(node)
        all_args = node.args.args + node.args.kwonlyargs

        for arg in all_args:
            if arg.arg in ("self", "cls", "request", "response"):
                continue
            if is_depends_default(defaults.get(arg.arg)):
                continue
            # Skip simple path/query params (str, int, float, bool, bytes)
            if isinstance(arg.annotation, ast.Name) and arg.annotation.id in SIMPLE_TYPES:
                continue
            if is_raw_type(arg.annotation):
                warnings.append(
                    f"{filepath.name}:{node.lineno}: route '{node.name}' parameter "
                    f"'{arg.arg}' uses a raw type. "
                    f"Route parameter must be a Pydantic BaseModel. "
                    f"Replace dict with a typed schema in app/schemas/."
                )

    return warnings


def main() -> int:
    files = sorted(ROUTERS_DIR.glob("*.py")) + [MAIN_FILE]
    all_warnings: list[str] = []
    for filepath in files:
        all_warnings.extend(check_file(filepath))

    if all_warnings:
        for w in all_warnings:
            print(f"WARNING: {w}", file=sys.stderr)
        print(
            f"\nboundary_checker: {len(all_warnings)} advisory warning(s). "
            f"Consider using typed Pydantic schemas for all request bodies.",
            file=sys.stderr,
        )
    else:
        print("boundary_checker: all route parameters use typed schemas.")

    return 0  # advisory only — never fails CI


if __name__ == "__main__":
    sys.exit(main())
