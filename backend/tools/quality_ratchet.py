"""Code-quality ratchet: debt already in the tree may only shrink.

Each check lists today's offenders in quality_baseline.json. A new offender fails,
and so does a baseline entry that no longer offends, so the file shrinks as debt is
paid. Targets and measurements are in docs/roadmap.md, "Code quality to 1.0".

Run:      uv run python tools/quality_ratchet.py
Shrink:   uv run python tools/quality_ratchet.py --prune   (drops fixed entries only)
"""

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
APP = BACKEND / "app"
TESTS = BACKEND / "tests"
BASELINE = Path(__file__).resolve().parent / "quality_baseline.json"

# radon is run pinned rather than locked: it is a CI tool, not an app dependency.
# Python 3.13 because radon parses with the running interpreter's grammar.
RADON = ["uvx", "--python", "3.13", "radon@6.0.1"]

MAX_FUNCTION_LINES = 120
MAX_COMPLEXITY = 20
# I-23 freezes the table DDL in one function; splitting it changes nothing.
LENGTH_EXEMPT = {"app/db_init.py::create_all_tables"}

SQL_RE = re.compile(r"\bselect\(|session\.execute\(")
UNSTABLE_RE = re.compile(r"pytest\.mark\.unstable\b")


def _rel(path: Path) -> str:
    return path.relative_to(BACKEND).as_posix()


def long_functions() -> set[str]:
    found: set[str] = set()

    def visit(node: ast.AST, prefix: str, rel: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef):
                    lines = (child.end_lineno or child.lineno) - child.lineno + 1
                    if lines > MAX_FUNCTION_LINES:
                        found.add(f"{rel}::{name}")
                visit(child, f"{name}.", rel)

    for path in sorted(APP.rglob("*.py")):
        visit(ast.parse(path.read_text(encoding="utf-8")), "", _rel(path))
    return found - LENGTH_EXEMPT


def _radon(*args: str) -> dict:
    cmd = [*RADON, *args, "-j", "app"]
    out = subprocess.run(cmd, cwd=BACKEND, check=True, capture_output=True, text=True)
    data = json.loads(out.stdout)
    unparsed = [f for f, v in data.items() if isinstance(v, dict) and "error" in v]
    if unparsed:
        # A file radon cannot parse would silently drop out of every count.
        sys.exit(f"radon could not parse: {unparsed}")
    return data


def complexity() -> tuple[set[str], int]:
    over_max: set[str] = set()
    over_10 = 0
    for path, blocks in _radon("cc").items():
        for block in blocks:
            if block["type"] == "class":
                continue
            owner = block.get("classname")
            name = f"{owner}.{block['name']}" if owner else block["name"]
            over_10 += block["complexity"] > 10
            if block["complexity"] > MAX_COMPLEXITY:
                over_max.add(f"{path}::{name}")
    return over_max, over_10


def maintainability_below_a() -> set[str]:
    return {path for path, result in _radon("mi").items() if result["rank"] != "A"}


def _count_per_file(root: Path, pattern: re.Pattern[str], skip: str = "") -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        rel = _rel(path)
        if skip and rel.startswith(skip):
            continue
        n = len(pattern.findall(path.read_text(encoding="utf-8")))
        if n:
            counts[rel] = n
    return counts


def measure() -> dict:
    over_max, over_10 = complexity()
    return {
        "long_functions": sorted(long_functions()),
        "complex_functions": sorted(over_max),
        "complexity_over_10": over_10,
        "maintainability_below_a": sorted(maintainability_below_a()),
        "sql_outside_repos": _count_per_file(APP, SQL_RE, skip="app/repos/"),
        "unstable_tests": _count_per_file(TESTS, UNSTABLE_RE),
    }


def compare(base: dict, now: dict) -> tuple[list[str], list[str]]:
    """Return (regressions, improvements not yet pruned from the baseline)."""
    worse: list[str] = []
    better: list[str] = []
    for key in ("long_functions", "complex_functions", "maintainability_below_a"):
        worse += [f"{key}: new offender {x}" for x in sorted(set(now[key]) - set(base[key]))]
        better += [f"{key}: {x} is fixed" for x in sorted(set(base[key]) - set(now[key]))]
    was, is_ = base["complexity_over_10"], now["complexity_over_10"]
    if is_ > was:
        worse.append(f"complexity_over_10: {was} -> {is_}")
    elif is_ < was:
        better.append(f"complexity_over_10: {was} -> {is_}")
    for key in ("sql_outside_repos", "unstable_tests"):
        for path in sorted(set(base[key]) | set(now[key])):
            was, is_ = base[key].get(path, 0), now[key].get(path, 0)
            if is_ > was:
                worse.append(f"{key}: {path} {was} -> {is_}")
            elif is_ < was:
                better.append(f"{key}: {path} {was} -> {is_}")
    return worse, better


def prune(base: dict, now: dict) -> dict:
    """The baseline with fixed entries removed; never adds an offender."""
    out = dict(base)
    for key in ("long_functions", "complex_functions", "maintainability_below_a"):
        out[key] = sorted(set(base[key]) & set(now[key]))
    out["complexity_over_10"] = min(base["complexity_over_10"], now["complexity_over_10"])
    for key in ("sql_outside_repos", "unstable_tests"):
        current = now[key]
        out[key] = {p: min(n, current[p]) for p, n in base[key].items() if current.get(p)}
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prune", action="store_true", help="drop fixed entries from the baseline")
    args = parser.parse_args()

    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    now = measure()
    worse, better = compare(base, now)

    if args.prune:
        BASELINE.write_text(json.dumps(prune(base, now), indent=2) + "\n", encoding="utf-8")
        print(f"quality baseline pruned ({len(better)} improvements recorded)")
    for line in worse:
        print(f"FAIL {line}")
    if not args.prune:
        for line in better:
            print(f"STALE {line} -- run tools/quality_ratchet.py --prune")
    if worse or (better and not args.prune):
        return 1
    print("quality ratchet OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
