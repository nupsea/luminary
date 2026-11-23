"""SDK 0.2: what a connector author gets instead of copying it from another connector (#542)."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from app.exceptions import LuminaryError
from tests.connector_fixture import SDK


@pytest.fixture
def sdk(monkeypatch):
    monkeypatch.syspath_prepend(str(SDK / "src"))
    import luminary_source_sdk

    return luminary_source_sdk


def test_the_polite_client_reads_waits_and_names_each_refusal(sdk):
    from luminary_source_sdk.client import PoliteClient
    from luminary_source_sdk.testing import serve_pages

    pages = {"/ok": "<p>fine</p>", "/gone": (404, "x"), "/private": (401, "x")}
    with serve_pages(pages) as base:
        client = PoliteClient("ua", delay_s=0.2, messages={404: "the page is missing"})
        started = time.monotonic()
        assert client.get_text(f"{base}/ok") == (f"{base}/ok", "<p>fine</p>")
        with pytest.raises(sdk.ConnectorError) as gone:
            client.get_text(f"{base}/gone")
        assert time.monotonic() - started >= 0.2
        assert (gone.value.code, gone.value.message) == (
            "source",
            f"{base}/gone answered 404: the page is missing",
        )
        with pytest.raises(sdk.ConnectorError) as private:
            client.get_text(f"{base}/private")
        assert private.value.code == "auth"


def test_a_dropped_connection_is_retried_then_reported(sdk):
    from luminary_source_sdk.client import PoliteClient
    from luminary_source_sdk.testing import serve_pages

    with serve_pages({}) as base:
        pass  # the server is gone: every request is refused
    attempts = []
    client = PoliteClient("ua", retries=2, backoff_s=0)
    original = client._get_once
    client._get_once = lambda url, headers: (attempts.append(url), original(url, headers))[1]
    with pytest.raises(sdk.ConnectorError) as failed:
        client.get_text(f"{base}/x")
    assert failed.value.code == "source" and len(attempts) == 3


def test_main_html_keeps_the_main_and_the_title(sdk):
    from luminary_source_sdk.pages import main_html

    page = "<title> A  page </title><nav>menu</nav><main><h1>A</h1><p>x &amp; y<br>z</p></main>"
    assert main_html(page) == ("A page", "<h1>A</h1><p>x &amp; y<br>z</p>")
    assert main_html("<p>no main</p>") == ("", "")


def test_progress_never_goes_back_or_reaches_one(sdk):
    from luminary_source_sdk.progress import Progress

    seen: list[float] = []
    progress = Progress(lambda f, s: seen.append(f), "pages")
    progress.update(5, 5)
    progress.update(6, 30)  # more found: the estimate drops, the report does not
    progress.update(99, 0)
    assert seen == [0.5, 0.5, 0.99]


def test_a_url_connector_is_described_by_its_attributes(sdk, tmp_path):
    from luminary_source_sdk.bases import UrlConnector

    class Site(UrlConnector):
        NAME, VERSION, LABEL = "site", "1.2.0", "Site"
        TERMS = sdk.Terms("Pages may be read.", "https://site.example/terms")
        URL_PREFIXES = ("https://site.example/docs/",)

        def fetch(self, input, credentials, bundle, report):
            url = self.claimed_url(input)
            bundle.add_section("p", "Page", markdown="Text of the page, long enough.")
            self.finish(bundle, title="Site docs", source_url=url)

    described = Site().describe().to_json()
    assert described["name"] == "site" and described["url_prefixes"] == [
        "https://site.example/docs/"
    ]
    with pytest.raises(sdk.ConnectorError, match="not a link Site takes"):
        Site().claimed_url({"url": "https://elsewhere.example/"})
    writer = sdk.BundleWriter(tmp_path / "b")
    Site().fetch({"url": "https://site.example/docs/a"}, {}, writer, lambda f, s: None)
    manifest = json.loads((tmp_path / "b" / "manifest.json").read_text())
    assert manifest["connector"] == {"name": "site", "version": "1.2.0"}
    assert manifest["terms"]["url"] == "https://site.example/terms"


def test_a_folder_connector_speaks_protocol_2_and_reads_the_file_handed_over(sdk, tmp_path):
    from luminary_source_sdk.bases import FolderConnector

    read: list[Path] = []

    class Notebooks(FolderConnector):
        NAME, VERSION = "notebooks", "0.1.0"
        TERMS = sdk.Terms("Reads files the user picked.", "https://example.org/terms")
        PATTERNS = ("*.note",)

        def fetch_file(self, path, bundle, report):
            read.append(path)

    described = Notebooks().describe().to_json()
    assert described["protocol"] == 2
    assert described["source"] == {
        "kind": "folder",
        "patterns": ["*.note"],
        "max_file_bytes": None,
    }
    note = tmp_path / "a.note"
    note.write_bytes(b"x")
    Notebooks().fetch({"file": str(note)}, {}, None, None)
    assert read == [note]
    with pytest.raises(sdk.ConnectorError, match="not a file"):
        Notebooks().fetch({"file": str(tmp_path / "missing.note")}, {}, None, None)


def test_a_new_project_fetches_and_validates_without_luminary(sdk, tmp_path, monkeypatch):
    from luminary_source_sdk.cli import new, validate
    from luminary_source_sdk.testing import run, serve_pages

    root = new("demo-site", tmp_path)
    monkeypatch.syspath_prepend(str(root / "src"))
    from luminary_demo_site import DemoSite

    page = "<title>Doc</title><main><h1>Doc</h1><p>Enough text to make a section.</p></main>"
    with serve_pages({"/a": page}) as base:
        monkeypatch.setattr(DemoSite, "URL_PREFIXES", (base + "/",))
        events = run(
            "luminary_demo_site:DemoSite", "fetch", input={"url": base + "/a"}, dest=tmp_path / "b"
        )
    assert events[-1]["event"] == "result", events[-1]
    # The template's terms are the placeholder, which validate refuses until they are filled.
    assert validate(tmp_path / "b") == ["terms.statement is still the template's placeholder"]


# --- validate never passes a bundle Luminary refuses ------------------------------------------


def _good(sdk, dest: Path) -> Path:
    writer = sdk.BundleWriter(dest)
    writer.add_section(
        "one", "One", markdown="A log is an append-only sequence of records on disk."
    )
    writer.finish(
        connector=("fixture", "0.1.0"),
        title="Fixture",
        terms=sdk.Terms("Fixture pages may be downloaded.", "https://fixture.example/terms"),
    )
    return dest


def _edit(bundle: Path, change) -> Path:
    manifest = json.loads((bundle / "manifest.json").read_text())
    change(manifest, bundle)
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    return bundle


_BROKEN = {
    "missing section file": lambda m, b: (b / m["sections"][0]["file"]).unlink(),
    "path outside the bundle": lambda m, b: m["sections"][0].update(file="../escape.md"),
    "unknown media": lambda m, b: m.update(media={"kind": "hologram"}),
    "no sections": lambda m, b: m.update(sections=[]),
    "another bundle version": lambda m, b: m.update(bundle_version=99),
    "duplicate section id": lambda m, b: m["sections"].append(dict(m["sections"][0])),
    "only short sections": lambda m, b: (b / m["sections"][0]["file"]).write_text("Too short."),
}


def _luminary_refuses(bundle: Path) -> bool:
    from app.scripts.check_bundle import read

    try:
        read(bundle)
    except LuminaryError:
        return True
    return False


def test_validate_and_luminary_both_accept_a_bundle_the_sdk_wrote(sdk, tmp_path):
    from luminary_source_sdk.cli import validate

    bundle = _good(sdk, tmp_path / "good")
    assert validate(bundle) == [] and not _luminary_refuses(bundle)


@pytest.mark.parametrize("case", sorted(_BROKEN))
def test_validate_refuses_every_bundle_luminary_refuses(sdk, tmp_path, case):
    from luminary_source_sdk.cli import validate

    bundle = _edit(_good(sdk, tmp_path / case.replace(" ", "-")), _BROKEN[case])
    assert _luminary_refuses(bundle), f"Luminary accepts {case}; drop it from the corpus"
    assert validate(bundle), f"validate passes a bundle Luminary refuses: {case}"
    shutil.rmtree(bundle)


def test_validate_holds_the_cores_section_minimum(sdk):
    from luminary_source_sdk.cli import MIN_SECTION_CHARS

    from app.services.parser import MIN_SECTION_CHARS as CORE

    assert MIN_SECTION_CHARS == CORE
