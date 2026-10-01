"""The quality ratchet fails on growth, flags fixed debt still listed, and prunes only."""

from tools.quality_ratchet import compare, prune


def _baseline(**overrides):
    base = {
        "long_functions": ["app/a.py::f"],
        "complex_functions": ["app/a.py::g"],
        "complexity_over_10": 5,
        "maintainability_below_a": ["app/a.py"],
        "sql_outside_repos": {"app/routers/x.py": 3},
        "unstable_tests": {"tests/test_x.py": 1},
        "content_type_refs": {"app/services/z.py": 2},
    }
    base.update(overrides)
    return base


def test_unchanged_is_clean():
    assert compare(_baseline(), _baseline()) == ([], [])


def test_new_offenders_fail():
    now = _baseline(
        long_functions=["app/a.py::f", "app/b.py::h"],
        complexity_over_10=6,
        sql_outside_repos={"app/routers/x.py": 3, "app/services/y.py": 1},
        unstable_tests={"tests/test_x.py": 2},
    )
    worse, better = compare(_baseline(), now)
    assert worse == [
        "long_functions: new offender app/b.py::h",
        "complexity_over_10: 5 -> 6",
        "sql_outside_repos: app/services/y.py 0 -> 1",
        "unstable_tests: tests/test_x.py 1 -> 2",
    ]
    assert better == []


def test_fixed_debt_left_in_baseline_is_reported():
    now = _baseline(complex_functions=[], sql_outside_repos={"app/routers/x.py": 1})
    worse, better = compare(_baseline(), now)
    assert worse == []
    assert better == [
        "complex_functions: app/a.py::g is fixed",
        "sql_outside_repos: app/routers/x.py 3 -> 1",
    ]


def test_prune_shrinks_and_never_adds():
    now = _baseline(
        long_functions=["app/b.py::h"],  # a.py::f fixed, b.py::h new
        complexity_over_10=9,
        sql_outside_repos={"app/routers/x.py": 1, "app/services/y.py": 4},
        unstable_tests={},
    )
    pruned = prune(_baseline(), now)
    assert pruned["long_functions"] == []
    assert pruned["complexity_over_10"] == 5
    assert pruned["sql_outside_repos"] == {"app/routers/x.py": 1}
    assert pruned["unstable_tests"] == {}
    # The new offenders are still regressions against the pruned baseline.
    worse, _ = compare(pruned, now)
    assert len(worse) == 3


def test_a_new_content_type_reader_fails():
    now = _baseline(content_type_refs={"app/services/z.py": 2, "app/services/new.py": 1})
    worse, _ = compare(_baseline(), now)
    assert worse == ["content_type_refs: app/services/new.py 0 -> 1"]
