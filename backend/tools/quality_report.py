"""Code-quality summary for a release's notes, measured at the tagged commit (#189).

Reads the coverage and knip outputs `release.yml` produces, adds the ratchet's own
measurements, and writes Markdown plus a JSON record the next release compares with.
Every input is required: a number that cannot be measured fails the run rather than
publishing a partial table.

Run from backend/:
  uv run python -m tools.quality_report --version 0.15.0 --backend-cov cov.json \
      --frontend-cov coverage-summary.json --knip knip.json [--previous prev.json] \
      --json-out quality-summary.json > quality-summary.md
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

from tools.quality_ratchet import BACKEND, RADON, measure

REPO = BACKEND.parent
FRONTEND = REPO / "frontend"

# (key, label, 1.0 target). Order is the table's order.
ROWS = [
    ("long_functions", "Functions over 120 lines", "0"),
    ("complex_functions", "Functions with cyclomatic complexity over 20", "0"),
    ("complexity_over_10", "Functions with cyclomatic complexity over 10", "under 5% of functions"),
    ("maintainability_below_a", "Files with maintainability index below A", "0"),
    (
        "sql_outside_repos",
        "SQL statements outside `app/repos/`",
        "0 in routers by 0.17, 0 everywhere by 1.0",
    ),
    ("unstable_tests", "Tests marked `unstable` (quarantined)", "0"),
    ("knip", "Unused frontend files, exports, dependencies (knip)", "0"),
    ("backend_coverage", "Backend test coverage (statements)", "at least 80% on changed lines"),
    (
        "frontend_coverage",
        "Frontend test coverage (lines / statements / branches)",
        "at least 80% on changed lines",
    ),
]
FRONTEND_COVERAGE_KEYS = ("lines", "statements", "branches")


def _fail(message: str) -> NoReturn:
    sys.exit(f"quality_report: {message}")


def _load(path: Path, what: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _fail(f"cannot read {what} from {path}: {exc}")


def _match(pattern: str, path: Path, what: str) -> re.Match[str]:
    found = re.search(pattern, path.read_text(encoding="utf-8"))
    if found is None:
        _fail(f"no {what} in {path}")
    return found


def _pct(value: object, what: str) -> float:
    # 0% means the run measured nothing, not that nothing is covered.
    if not isinstance(value, int | float) or not 0 < value <= 100:
        _fail(f"{what} is {value!r}, not a measured percentage")
    return round(float(value), 2)


def _knip_count(report: dict) -> int:
    """Every reported item: unused files plus each list on each file's issue entry."""
    if "files" not in report or "issues" not in report:
        _fail("knip report lacks `files` or `issues`")
    items = len(report["files"])
    for issue in report["issues"]:
        items += sum(len(v) for k, v in issue.items() if isinstance(v, list) and k != "owners")
    return items


def _node_version(package: str) -> str:
    return _load(FRONTEND / "node_modules" / package / "package.json", package)["version"]


def _check_floors(record: dict) -> None:
    """A total below the floor `make ci` enforces means the suite did not all run."""
    metrics, floors = record["metrics"], record["floors"]
    below = [] if metrics["backend_coverage"] >= floors["backend"] else ["backend"]
    below += [
        f"frontend {key}"
        for key in FRONTEND_COVERAGE_KEYS
        if metrics["frontend_coverage"][key] < floors["frontend"][key]
    ]
    if below:
        _fail(f"coverage below its floor for {', '.join(below)}: was the whole suite run?")


def build_record(version: str, backend_cov: dict, frontend_cov: dict, knip: dict) -> dict:
    ratchet = measure()
    thresholds = _match(r"thresholds:\s*\{([^}]*)\}", FRONTEND / "vitest.config.ts", "floors")
    fe_floors = dict(re.findall(r"(\w+):\s*(\d+)", thresholds.group(1)))
    if missing := [k for k in FRONTEND_COVERAGE_KEYS if k not in fe_floors]:
        _fail(f"no frontend floor for {missing}")
    frontend_total = frontend_cov.get("total", {})
    commit = subprocess.run(
        ["git", "rev-parse", "--short=8", "HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    record = {
        "version": version,
        "commit": commit,
        "metrics": {
            "long_functions": len(ratchet["long_functions"]),
            "complex_functions": len(ratchet["complex_functions"]),
            "complexity_over_10": ratchet["complexity_over_10"],
            "maintainability_below_a": len(ratchet["maintainability_below_a"]),
            "sql_outside_repos": sum(ratchet["sql_outside_repos"].values()),
            "sql_files": len(ratchet["sql_outside_repos"]),
            "unstable_tests": sum(ratchet["unstable_tests"].values()),
            "knip": _knip_count(knip),
            "backend_coverage": _pct(
                backend_cov.get("totals", {}).get("percent_covered"), "backend coverage"
            ),
            "frontend_coverage": {
                key: _pct(frontend_total.get(key, {}).get("pct"), f"frontend {key} coverage")
                for key in FRONTEND_COVERAGE_KEYS
            },
        },
        "floors": {
            "backend": int(
                _match(r"BACKEND_COVERAGE_FLOOR \?= (\d+)", REPO / "Makefile", "floor").group(1)
            ),
            "frontend": {key: int(fe_floors[key]) for key in FRONTEND_COVERAGE_KEYS},
        },
        "tools": {
            "radon": RADON[-1].split("@")[1],
            "coverage.py": backend_cov.get("meta", {}).get("version")
            or _fail("no coverage.py version"),
            "pytest-cov": _match(r"pytest-cov==([\d.]+)", REPO / "Makefile", "pytest-cov").group(1),
            "vitest": _node_version("vitest"),
            "knip": _node_version("knip"),
        },
    }
    _check_floors(record)
    return record


def _cell(key: str, record: dict) -> str:
    metrics, floors = record["metrics"], record.get("floors", {})
    if key == "sql_outside_repos":
        return f"{metrics[key]} in {metrics['sql_files']} files"
    if key == "backend_coverage":
        return f"{metrics[key]:.2f}% (floor {floors['backend']})"
    if key == "frontend_coverage":
        cov, fl = metrics[key], floors["frontend"]
        pcts = " / ".join(f"{cov[k]:.2f}%" for k in FRONTEND_COVERAGE_KEYS)
        return f"{pcts} (floors {' / '.join(str(fl[k]) for k in FRONTEND_COVERAGE_KEYS)})"
    return str(metrics[key])


def render(record: dict, previous: dict | None) -> str:
    version = record["version"]
    header = f"| Metric | v{version} |"
    rule = "|---|---|"
    if previous:
        header += f" v{previous['version']} |"
        rule += "---|"
    lines = [
        f"## Code quality at v{version}",
        "",
        f"Measured on the tagged commit `{record['commit']}` by `release.yml`. "
        "`make ci` fails if any ratchet metric grows or a coverage total drops below its floor.",
        "",
        f"{header} 1.0 target |",
        f"{rule}---|",
    ]
    for key, label, target in ROWS:
        row = f"| {label} | {_cell(key, record)} |"
        if previous:
            row += f" {_cell(key, previous) if key in previous['metrics'] else 'not measured'} |"
        lines.append(f"{row} {target} |")
    lines.append("")
    if previous is None:
        lines.append(
            "No earlier release carries a generated summary, so there is nothing to compare with."
        )
        lines.append("")
    tools = ", ".join(f"{name} {v}" for name, v in record["tools"].items())
    lines += [
        f"Tools: {tools}.",
        "",
        f"To reproduce, check out `v{version}` and run `make ci`, which prints both coverage "
        "totals and runs knip, and `cd backend && uv run python -c "
        '"import tools.quality_ratchet as q; print(q.measure())"`.',
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--backend-cov", type=Path, required=True, help="coverage.py JSON report")
    parser.add_argument("--frontend-cov", type=Path, required=True, help="vitest json-summary")
    parser.add_argument("--knip", type=Path, required=True, help="knip --reporter json output")
    parser.add_argument("--previous", type=Path, help="the previous release's JSON record")
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()

    record = build_record(
        args.version,
        _load(args.backend_cov, "backend coverage"),
        _load(args.frontend_cov, "frontend coverage"),
        _load(args.knip, "knip report"),
    )
    previous = _load(args.previous, "previous summary") if args.previous else None
    args.json_out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(render(record, previous))
    return 0


if __name__ == "__main__":
    sys.exit(main())
