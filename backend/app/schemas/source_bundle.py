"""The source bundle's manifest: what a connector hands the core (`docs/roadmap.md` §7).

The one definition. `packages/luminary-source-sdk/schema/source-bundle.schema.json` is its
published form, and `tests/test_source_bundle.py` fails when the two differ.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

BUNDLE_VERSION = 1

# A path inside the bundle, written with forward slashes. The importer resolves each one
# against the bundle and refuses any that leaves it; the pattern only shapes the obvious.
SectionPath = Annotated[str, Field(pattern=r"^sections/[^\\:]+$", max_length=512)]
AssetPath = Annotated[str, Field(pattern=r"^assets/[^\\:]+$", max_length=512)]
WebUrl = Annotated[str, Field(pattern=r"^https?://", max_length=2048)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Connector(_Strict):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    version: str = Field(min_length=1, max_length=64)


class Terms(_Strict):
    """What the source's own terms page says about this work, quoted, and where it says it."""

    statement: str = Field(min_length=1, max_length=4000)
    url: WebUrl


class TextMedia(_Strict):
    kind: Literal["text"]


class AudioMedia(_Strict):
    kind: Literal["audio"]
    audio: AssetPath
    captions: AssetPath | None = None


class YoutubeMedia(_Strict):
    kind: Literal["youtube"]
    url: WebUrl
    audio: AssetPath
    captions: AssetPath | None = None


class BundleSection(_Strict):
    """One entry of the table of contents, in reading order; `level` makes the tree."""

    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    heading: str = Field(min_length=1, max_length=500)
    level: int = Field(ge=1, le=6)
    file: SectionPath
    source_url: WebUrl | None = None


class BundleManifest(_Strict):
    bundle_version: Literal[1]
    connector: Connector
    title: str = Field(min_length=1, max_length=500)
    authors: list[Annotated[str, Field(min_length=1, max_length=200)]] = []
    cover: AssetPath | None = None
    source_url: WebUrl | None = None
    locator: str | None = Field(None, min_length=1, max_length=500)
    media: TextMedia | AudioMedia | YoutubeMedia = Field(discriminator="kind")
    terms: Terms
    tags: list[Annotated[str, Field(min_length=1, max_length=100)]] = []
    # What the source says about itself (a talk's description, its chapter titles): the
    # metadata the transcript vocabulary is drawn from (I-66), never document text.
    description: str | None = Field(None, max_length=20000)
    chapters: list[Annotated[str, Field(min_length=1, max_length=500)]] = []
    sections: list[BundleSection] = []
