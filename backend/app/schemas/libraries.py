"""The libraries on this machine, as Settings lists, switches, exports and imports them."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LibraryItem(BaseModel):
    id: str
    active: bool
    # What the library holds on disk: its database, vectors and files.
    bytes: int


class LibraryList(BaseModel):
    active: str
    libraries: list[LibraryItem]


class LibraryName(BaseModel):
    library: str = Field(..., min_length=1, max_length=63)


class LibraryContents(BaseModel):
    documents: int
    flashcards: int
    notes: int


class LibraryExport(BaseModel):
    library: str
    path: str
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
