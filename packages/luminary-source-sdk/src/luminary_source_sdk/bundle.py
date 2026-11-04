"""Write a source bundle: `manifest.json`, `sections/`, `assets/`.

The schema is `source-bundle.schema.json` beside this module. Luminary validates every bundle
again when it stores one, so this writer only keeps a connector from writing an obviously
broken one.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

from luminary_source_sdk.protocol import Terms

BUNDLE_VERSION = 1
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")


class BundleError(ValueError):
    """The connector asked for a bundle the format does not allow."""


def _safe(name: str) -> str:
    if not _SAFE_NAME.match(name) or ".." in PurePosixPath(name).parts:
        raise BundleError(f"{name!r} is not a safe path inside a bundle")
    return name


class BundleWriter:
    """Builds one bundle in `dest`, the directory the core named for this fetch."""

    def __init__(self, dest: Path) -> None:
        self.dest = Path(dest)
        if self.dest.exists() and any(self.dest.iterdir()):
            raise BundleError(f"{self.dest} is not empty")
        self.dest.mkdir(parents=True, exist_ok=True)
        self._sections: list[dict[str, Any]] = []

    def add_section(
        self,
        id: str,
        heading: str,
        *,
        html: str | None = None,
        markdown: str | None = None,
        level: int = 1,
        source_url: str | None = None,
    ) -> None:
        """One table-of-contents entry, in reading order. Give its text as HTML or Markdown."""
        if (html is None) == (markdown is None):
            raise BundleError("a section takes exactly one of html= or markdown=")
        if any(s["id"] == id for s in self._sections):
            raise BundleError(f"section id {id!r} is already used")
        rel = f"sections/{_safe(id)}.{'html' if html is not None else 'md'}"
        path = self.dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html if html is not None else markdown or "", encoding="utf-8")
        entry: dict[str, Any] = {"id": id, "heading": heading, "level": level, "file": rel}
        if source_url:
            entry["source_url"] = source_url
        self._sections.append(entry)

    def add_asset(self, name: str, data: bytes) -> str:
        """Store an image, audio file or caption track; returns its path for the manifest."""
        rel = f"assets/{_safe(name)}"
        path = self.dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return rel

    def add_asset_file(self, name: str, source: Path) -> str:
        """Move a file already on disk into the bundle (an hour of audio is not read into
        memory); returns its path for the manifest."""
        rel = f"assets/{_safe(name)}"
        path = self.dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), path)
        return rel

    def finish(
        self,
        *,
        connector: tuple[str, str],
        title: str,
        terms: Terms,
        media: dict[str, Any] | None = None,
        authors: list[str] | None = None,
        cover: str | None = None,
        source_url: str | None = None,
        locator: str | None = None,
        tags: list[str] | None = None,
        description: str | None = None,
        chapters: list[str] | None = None,
        labels: list[str] | None = None,
    ) -> Path:
        """Write `manifest.json`. Call once, after every section and asset."""
        media = media or {"kind": "text"}
        if media.get("kind") == "text" and not self._sections:
            raise BundleError("a text bundle needs at least one section")
        manifest: dict[str, Any] = {
            "bundle_version": BUNDLE_VERSION,
            "connector": {"name": connector[0], "version": connector[1]},
            "title": title,
            "authors": list(authors or []),
            "media": media,
            "terms": {"statement": terms.statement, "url": terms.url},
            "tags": list(tags or []),
            "chapters": list(chapters or []),
            "labels": list(labels or []),
            "sections": self._sections,
        }
        optional = {"cover": cover, "source_url": source_url, "locator": locator,
                    "description": description}  # fmt: skip
        manifest |= {key: value for key, value in optional.items() if value is not None}
        path = self.dest / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
