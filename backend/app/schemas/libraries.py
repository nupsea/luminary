"""The libraries on this machine, as the app lists, names, switches, removes and moves them."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

LibraryColor = Literal["slate", "blue", "green", "amber", "rose", "violet", "teal", "orange"]


class LibraryContents(BaseModel):
    documents: int
    flashcards: int
    notes: int


class LibraryItem(BaseModel):
    id: str
    active: bool
    # What the library holds on disk: its database, vectors and files.
    bytes: int
    name: str | None = None
    color: LibraryColor | None = None
    # None when its database could not be read.
    contents: LibraryContents | None = None


class LibraryList(BaseModel):
    active: str
    libraries: list[LibraryItem]


class LibraryName(BaseModel):
    library: str = Field(..., min_length=1, max_length=63)


class LibraryProfile(BaseModel):
    name: str | None = Field(None, max_length=40)
    color: LibraryColor | None = None


class LibraryCreate(LibraryProfile):
    library: str = Field(..., min_length=1, max_length=63)


class LibraryRemoved(BaseModel):
    library: str
    # False: hidden now, its files deleted when Luminary next starts.
    removed_now: bool


class ArchiveItem(BaseModel):
    name: str
    bytes: int
    modified: datetime


class DestinationItem(BaseModel):
    id: str
    kind: str
    name: str
    path: str
    archives: list[ArchiveItem]


class DestinationList(BaseModel):
    destinations: list[DestinationItem]


class ArchiveRef(BaseModel):
    destination: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=255)


class ExportRequest(BaseModel):
    destination: str = "exports"


class ImportFromFolder(ArchiveRef):
    library: str = Field(..., min_length=1, max_length=63)
    activate: bool = False


class LibraryExport(BaseModel):
    library: str
    destination: str
    destination_name: str
    path: str
    # The archive's file name, which reveals it in its folder.
    name: str
    bytes: int
    files: int
    contents: LibraryContents


class LibraryImport(BaseModel):
    library: str
    active: bool
    # Where the snapshot came from, so the user can tell it is the one they meant.
    source_library: str
    created_at: str
    app_version: str
    files: int
    contents: LibraryContents
    name: str | None = None
    color: LibraryColor | None = None
