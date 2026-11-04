"""The connector conformance kit (#438) passes a faithful connector and fails each defect it
names, through Luminary's own importer."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from tests.connector_fixture import SDK

BACKEND = Path(__file__).resolve().parents[1]
BODY = "A log is an append-only sequence of records stored on disk. " * 3
TOC = ["Introduction", "Storage", "Replication"]
NAV = "Edit this page on GitHub"

_SOURCE = f"""
from luminary_source_sdk import Connector, Description, Terms

TERMS = Terms("Book pages may be downloaded for personal study.", "https://book.example/terms")
BODY = {BODY!r}
TOC = {TOC!r}
NAV = {NAV!r}


class Book(Connector):
    def describe(self):
        return Description(name="book", version="0.1.0", licence="Apache-2.0", terms=TERMS,
                           url_prefixes=["https://book.example/"])

    def fetch(self, input, credentials, bundle, report):
        defect = input.get("defect", "")
        pages = list(TOC)
        if defect == "missing":
            pages.remove("Storage")
        if defect == "reordered":
            pages.reverse()
        if defect == "extra":
            pages.append("Search results")
        for n, heading in enumerate(pages):
            text = "" if defect == "empty" and n == 1 else BODY
            if defect == "short":
                text = "Too short."
            footer = f"<div>{{NAV}}</div>" if defect == "chrome" else ""
            html = f"<h1>{{heading}}</h1><p>{{text}}</p>{{footer}}"
            bundle.add_section(f"p{{n}}", heading, html=html)
            report(1 - n / 10 if defect == "progress" else n / len(pages), "downloading")
        name = "other" if defect == "unnamed" else "book"
        bundle.finish(connector=(name, "0.1.0"), title="A Book", terms=TERMS,
                      source_url=input["url"])
"""


@pytest.fixture
def kit(tmp_path, monkeypatch):
    package = tmp_path / "src" / "book_connector"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(_SOURCE)
    monkeypatch.syspath_prepend(str(tmp_path / "src"))
    monkeypatch.delitem(sys.modules, "book_connector", raising=False)
    monkeypatch.syspath_prepend(str(SDK / "src"))
    from luminary_source_sdk import conformance

    return conformance, package


def _importer() -> list[str]:
    return [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(BACKEND)!r}); "
            "from app.scripts.check_bundle import main; sys.exit(main(sys.argv[1:]))"]  # fmt: skip


def _run(kit, tmp_path, *, defect="", url="https://book.example/intro", importer=True):
    conformance, _ = kit
    truth = conformance.Truth({"url": url, "defect": defect}, TOC, chrome=[NAV])
    findings = conformance.conform(
        "book_connector:Book", truth, tmp_path / "bundle", _importer() if importer else None
    )
    return {f.check: f for f in findings}


def test_a_faithful_connector_passes_every_check(kit, tmp_path):
    findings = _run(kit, tmp_path)

    assert [c for c, f in findings.items() if not f.passed] == []
    assert findings["Luminary imports it"].detail == "3 sections"
    assert len(findings) == 14


@pytest.mark.parametrize(
    ("defect", "failed"),
    [
        ("missing", ["pages found"]),
        ("extra", ["no extra pages"]),
        ("reordered", ["section order"]),
        ("empty", ["no empty sections"]),
        ("chrome", ["chrome stripped", "chrome stripped after import"]),
        ("progress", ["progress"]),
        ("unnamed", ["manifest names the connector"]),
        ("short", ["Luminary imports it"]),
    ],
)
def test_each_defect_fails_its_own_check(kit, tmp_path, defect, failed):
    findings = _run(kit, tmp_path, defect=defect)

    assert [c for c, f in findings.items() if not f.passed] == failed


def test_a_link_the_connector_does_not_claim_fails(kit, tmp_path):
    findings = _run(kit, tmp_path, url="https://elsewhere.example/intro", importer=False)

    assert not findings["claims the link"].passed


def test_a_connector_importing_luminary_fails(kit, tmp_path):
    _, package = kit
    (package / "helpers.py").write_text("from app.services import source_bundle\n")

    finding = _run(kit, tmp_path, importer=False)["no app import"]

    assert not finding.passed
    assert "helpers.py:1" in finding.detail


def test_the_kit_runs_from_the_command_line(kit, tmp_path, capsys):
    conformance, _ = kit
    truth = tmp_path / "truth.json"
    truth.write_text(json.dumps({"input": {"url": "https://book.example/"}, "toc": TOC}))

    status = conformance.main(["book_connector:Book", str(truth)])

    assert status == 0
    assert capsys.readouterr().out.splitlines()[0] == "PASS  describe"


def test_check_bundle_reports_a_refusal(tmp_path, capsys):
    from app.scripts.check_bundle import main

    (tmp_path / "b").mkdir()
    assert main([str(tmp_path / "b")]) == 1
    assert "error" in json.loads(capsys.readouterr().out)


def test_visible_text_drops_tags_and_scripts(kit):
    conformance, _ = kit
    html = textwrap.dedent("""<p>Kept <b>text</b></p><script>var hidden = 1;</script>""")

    assert conformance.visible_text(html, ".html") == "Kept text"


def test_a_description_install_would_refuse_fails(kit):
    conformance, _ = kit
    truth = conformance.Truth({"url": "https://book.example/"}, TOC)
    desc = {"name": "book", "version": "0.1.0", "licence": "Apache-2.0",
            "terms": {"statement": "May be read.", "url": "http://book.example/terms"},
            "url_prefixes": ["https://book.example/", "book.example"]}  # fmt: skip

    finding = conformance.check_description(desc, truth)[0]

    assert not finding.passed
    assert "an https terms.url" in finding.detail
    assert "'book.example'" in finding.detail
