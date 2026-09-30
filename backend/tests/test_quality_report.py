"""The release quality summary refuses unmeasured numbers and compares with the last release."""

import pytest

import tools.quality_report as report

RATCHET = {
    "long_functions": ["app/a.py::f", "app/b.py::g"],
    "complex_functions": ["app/a.py::f"],
    "complexity_over_10": 7,
    "maintainability_below_a": [],
    "sql_outside_repos": {"app/routers/x.py": 3, "app/services/y.py": 2},
    "unstable_tests": {},
}
BACKEND_COV = {"meta": {"version": "7.16.2"}, "totals": {"percent_covered": 78.123}}
FRONTEND_COV = {
    "total": {
        "lines": {"pct": 16.0},
        "statements": {"pct": 16.35},
        "branches": {"pct": 13.94},
    }
}
KNIP_CLEAN = {"files": [], "issues": []}


@pytest.fixture(autouse=True)
def _no_external_tools(monkeypatch):
    monkeypatch.setattr(report, "measure", lambda: RATCHET)
    monkeypatch.setattr(report, "_node_version", lambda package: "1.0.0")


def _record(**overrides):
    args = {"backend_cov": BACKEND_COV, "frontend_cov": FRONTEND_COV, "knip": KNIP_CLEAN}
    args.update(overrides)
    return report.build_record("0.15.0", **args)


def test_record_carries_every_measured_number():
    metrics = _record()["metrics"]
    assert metrics["long_functions"] == 2
    assert (metrics["sql_outside_repos"], metrics["sql_files"]) == (5, 2)
    assert metrics["backend_coverage"] == 78.12
    assert metrics["frontend_coverage"] == {"lines": 16.0, "statements": 16.35, "branches": 13.94}
    assert metrics["knip"] == 0


def test_knip_counts_unused_files_and_each_listed_item():
    knip = {
        "files": ["src/dead.ts"],
        "issues": [
            {
                "file": "src/a.ts",
                "owners": ["@team"],
                "exports": [{"name": "x"}, {"name": "y"}],
                "dependencies": [{"name": "left-pad"}],
            }
        ],
    }
    assert _record(knip=knip)["metrics"]["knip"] == 4


@pytest.mark.parametrize(
    "backend_cov",
    [
        {"meta": {"version": "7"}, "totals": {"percent_covered": 0}},
        {"meta": {"version": "7"}, "totals": {}},
        {"meta": {"version": "7"}},
    ],
)
def test_an_unmeasured_coverage_fails_rather_than_publishing(backend_cov):
    with pytest.raises(SystemExit, match="not a measured percentage"):
        _record(backend_cov=backend_cov)


def test_coverage_below_its_floor_fails_as_a_partial_run():
    partial = {"meta": {"version": "7"}, "totals": {"percent_covered": 6.7}}
    with pytest.raises(SystemExit, match="below its floor for backend"):
        _record(backend_cov=partial)


def test_a_malformed_knip_report_fails():
    with pytest.raises(SystemExit, match="knip report"):
        _record(knip={"issues": []})


def test_the_first_generated_summary_says_there_is_nothing_to_compare():
    text = report.render(_record(), previous=None)
    assert "| Metric | v0.15.0 | 1.0 target |" in text
    assert "| Functions over 120 lines | 2 | 0 |" in text
    assert "5 in 2 files" in text
    assert "nothing to compare with" in text


def test_a_previous_summary_adds_its_column():
    previous = _record()
    previous["version"] = "0.14.9"
    previous["metrics"]["long_functions"] = 3
    del previous["metrics"]["knip"]
    text = report.render(_record(), previous)
    assert "| Metric | v0.15.0 | v0.14.9 | 1.0 target |" in text
    assert "| Functions over 120 lines | 2 | 3 | 0 |" in text
    assert "| 0 | not measured | 0 |" in text
    assert "nothing to compare with" not in text
