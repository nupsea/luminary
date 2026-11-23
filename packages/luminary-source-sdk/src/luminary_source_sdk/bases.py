"""Connectors described by class attributes, so a new one is its source's specifics and nothing
it has to restate: `describe`, the claim on a link, and what `finish` stamps on a bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from luminary_source_sdk.bundle import BundleWriter
from luminary_source_sdk.connector import Connector, ConnectorError, Report
from luminary_source_sdk.protocol import Description, Field, Source, Terms


class _Described(Connector):
    NAME: ClassVar[str]
    VERSION: ClassVar[str]
    TERMS: ClassVar[Terms]
    LICENCE: ClassVar[str] = "Apache-2.0"
    # What the user calls the source ("YouTube"); the name when empty.
    LABEL: ClassVar[str] = ""
    INPUTS: ClassVar[tuple[Field, ...]] = ()
    CREDENTIALS: ClassVar[tuple[Field, ...]] = ()
    PREVIEW: ClassVar[bool] = False
    MEDIA: ClassVar[tuple[str, ...]] = ("text",)
    TOOLS: ClassVar[tuple[str, ...]] = ()

    def _description(self, **more: Any) -> Description:
        return Description(
            name=self.NAME,
            version=self.VERSION,
            licence=self.LICENCE,
            terms=self.TERMS,
            label=self.LABEL,
            inputs=list(self.INPUTS),
            credentials=list(self.CREDENTIALS),
            preview=self.PREVIEW,
            media=list(self.MEDIA),
            tools=list(self.TOOLS),
            **more,
        )

    def finish(self, bundle: BundleWriter, *, title: str, **manifest: Any) -> None:
        """`bundle.finish`, with this connector's name, version and terms filled in."""
        bundle.finish(
            connector=(self.NAME, self.VERSION), terms=self.TERMS, title=title, **manifest
        )

    def user_agent(self, contact: str = "") -> str:
        return f"luminary-{self.NAME}/{self.VERSION}" + (f" (+{contact})" if contact else "")


class UrlConnector(_Described):
    """Takes a pasted link that starts with one of `URL_PREFIXES`."""

    URL_PREFIXES: ClassVar[tuple[str, ...]] = ()

    def describe(self) -> Description:
        return self._description(url_prefixes=list(self.URL_PREFIXES))

    def claimed_url(self, input: dict[str, Any]) -> str:
        """The input's link, or an `input` error naming what this connector takes."""
        url = str(input.get("url", ""))
        if not any(url.startswith(p) for p in self.URL_PREFIXES):
            raise ConnectorError("input", f"{url} is not a link {self.label_or_name} takes")
        return url

    @property
    def label_or_name(self) -> str:
        return self.LABEL or self.NAME


class FolderConnector(_Described):
    """Reads files from a folder the user picked (protocol 2, provisional until Luminary's folder
    source lands). Luminary lists the folder and hands each file over as `input["file"]`, a
    read-only copy: the connector never walks the folder itself."""

    PATTERNS: ClassVar[tuple[str, ...]] = ()
    MAX_FILE_BYTES: ClassVar[int | None] = None

    def describe(self) -> Description:
        return self._description(
            protocol=2,
            source=Source(
                kind="folder", patterns=list(self.PATTERNS), max_file_bytes=self.MAX_FILE_BYTES
            ),
        )

    def fetch(
        self,
        input: dict[str, Any],
        credentials: dict[str, Any],
        bundle: BundleWriter,
        report: Report,
    ) -> None:
        path = Path(str(input.get("file", "")))
        if not path.is_file():
            raise ConnectorError("input", f"{path} is not a file Luminary handed over")
        self.fetch_file(path, bundle, report)

    def fetch_file(self, path: Path, bundle: BundleWriter, report: Report) -> None:
        """Write the one file at *path* into *bundle*."""
        raise NotImplementedError
