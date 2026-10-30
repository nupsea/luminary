"""scripts/check_licences.py: a dependency ships only under a decided licence (I-71)."""

import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_licences", Path(__file__).resolve().parents[2] / "scripts" / "check_licences.py"
)
check_licences = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_licences)

REAL_POLICY = json.loads(check_licences.POLICY.read_text())


def _policy(**over):
    return {
        "allowed": REAL_POLICY["allowed"],
        "review": REAL_POLICY["review"],
        "declared": {},
        "exceptions": {},
        **over,
    }


@pytest.mark.parametrize(
    ("licence", "verdict"),
    [
        ("MIT", "allowed"),
        ("Apache Software License", "allowed"),
        ("MIT AND ISC", "allowed"),
        ("Apache-2.0 OR BSD-3-Clause", "allowed"),
        ("GPL-2.0-or-later", "review"),
        ("LGPL-2.1-or-later", "review"),
        ("GNU Affero General Public License v3 or later (AGPLv3+)", "review"),
        ("MIT OR GPL-3.0", "review"),
        ("CC-BY-NC-4.0", "review"),
        ("BUSL-1.1", "review"),
        ("MITRE", "unrecognised"),
        ("Custom", "unrecognised"),
    ],
)
def test_licence_strings_are_classified_by_the_policy(licence, verdict):
    assert check_licences.classify(licence, REAL_POLICY) == verdict


def test_a_copyleft_dependency_without_an_exception_fails():
    problems = check_licences.check({"python:mutagen": "GPL-2.0-or-later"}, _policy())
    assert len(problems) == 1 and "needs a decision" in problems[0]


def test_an_exception_holds_only_for_the_licence_it_was_granted_for():
    exceptions = {"python:pymupdf": {"licence": "AGPL-3.0", "reason": "r", "issue": "#1"}}
    assert (
        check_licences.check({"python:pymupdf": "AGPL-3.0"}, _policy(exceptions=exceptions)) == []
    )

    relicensed = check_licences.check(
        {"python:pymupdf": "SSPL-1.0"}, _policy(exceptions=exceptions)
    )
    assert len(relicensed) == 1 and "licence is now 'SSPL-1.0'" in relicensed[0]


def test_an_exception_for_a_package_that_no_longer_ships_fails():
    exceptions = {"python:gone": {"licence": "GPL-3.0", "reason": "r", "issue": "#1"}}
    problems = check_licences.check({}, _policy(exceptions=exceptions))
    assert len(problems) == 1 and "no longer ships" in problems[0]


def test_an_unstated_licence_needs_a_declared_one_and_that_one_is_classified_too():
    assert "declared" in check_licences.check({"npm:khroma": None}, _policy())[0]

    mit = {"npm:khroma": {"licence": "MIT", "source": "s"}}
    assert check_licences.check({"npm:khroma": None}, _policy(declared=mit)) == []

    gpl = {"npm:khroma": {"licence": "GPL-3.0", "source": "s"}}
    assert (
        "needs a decision" in check_licences.check({"npm:khroma": None}, _policy(declared=gpl))[0]
    )


def test_an_unrecognised_licence_fails_rather_than_passing():
    assert "matches no allowed pattern" in check_licences.check({"npm:x": "Custom"}, _policy())[0]


def test_npm_shipping_set_skips_dev_and_native_packages(tmp_path, monkeypatch):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package-lock.json").write_text(
        json.dumps(
            {
                "packages": {
                    "": {},
                    "node_modules/react": {"license": "MIT"},
                    "node_modules/vitest": {"license": "MIT", "dev": True},
                    "node_modules/@napi-rs/canvas-darwin-arm64": {
                        "license": "MIT",
                        "os": ["darwin"],
                    },
                    "node_modules/a/node_modules/react": {"license": "GPL-3.0", "version": "0.1.0"},
                }
            }
        )
    )
    monkeypatch.setattr(check_licences, "REPO", tmp_path)
    assert check_licences.shipping_npm() == {"react": "MIT", "react@0.1.0": "GPL-3.0"}


def test_every_exception_in_the_real_policy_carries_a_reason_and_an_issue():
    for key, entry in REAL_POLICY["exceptions"].items():
        assert entry["reason"].strip() and entry["issue"].startswith("#"), key
        assert check_licences.classify(entry["licence"], REAL_POLICY) != "allowed", key
    for key, entry in REAL_POLICY["declared"].items():
        assert entry["source"].strip(), key
