"""The libraries on this machine: list, create, switch, export and import.

Routes: GET /libraries, POST /libraries, PUT /libraries/active,
POST /libraries/import, POST /libraries/{library}/export

The app's own, like devices: a paired device works in the library it paired into and may
not see, switch or copy the others.
"""

import asyncio

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.exceptions import NotFound
from app.library import DEFAULT_LIBRARY, use_library
from app.runtime.library_work import serve_library
from app.runtime.request_auth import require_local
from app.schemas.libraries import (
    LibraryContents,
    LibraryExport,
    LibraryImport,
    LibraryItem,
    LibraryList,
    LibraryName,
)
from app.services import libraries as library_service

router = APIRouter(
    prefix="/libraries",
    tags=["libraries"],
    dependencies=[Depends(require_local("Libraries are managed from Luminary itself."))],
)


async def _open(library: str) -> None:
    if library != DEFAULT_LIBRARY:  # startup serves the default
        await serve_library(library)


async def _list() -> LibraryList:
    items = await asyncio.to_thread(library_service.list_libraries)
    return LibraryList(
        active=library_service.active_library(),
        libraries=[LibraryItem(id=i.id, active=i.active, bytes=i.bytes) for i in items],
    )


@router.get("", response_model=LibraryList)
async def list_libraries() -> LibraryList:
    return await _list()


@router.post("", response_model=LibraryList, status_code=201)
async def create_library(req: LibraryName) -> LibraryList:
    library = library_service.library_id(req.library)
    library_service.check_new_library(library)
    await _open(library)
    return await _list()


@router.put("/active", response_model=LibraryList)
async def switch_library(req: LibraryName) -> LibraryList:
    library = library_service.library_id(req.library)
    if not library_service.library_exists(library):
        raise NotFound(f"No library named {library!r} on this machine.")
    # Opened and migrated first: a library that cannot open is never switched to.
    await _open(library)
    library_service.set_active_library(library)
    return await _list()


@router.post("/import", response_model=LibraryImport, status_code=201)
async def import_library(
    file: UploadFile = File(...),
    library: str = Form(...),
    activate: bool = Form(False),
) -> LibraryImport:
    library = library_service.library_id(library)
    manifest = await library_service.import_archive(file.file, library)
    await _open(library)
    with use_library(library):
        contents = await library_service.contents()
    if activate:
        library_service.set_active_library(library)
    return LibraryImport(
        library=library,
        active=activate,
        source_library=manifest.library,
        created_at=manifest.created_at,
        app_version=manifest.app_version,
        files=len(manifest.files),
        contents=LibraryContents(**contents),
    )


@router.post("/{library}/export", response_model=LibraryExport)
async def export_library(library: str) -> LibraryExport:
    library = library_service.library_id(library)
    if not library_service.library_exists(library):
        raise NotFound(f"No library named {library!r} on this machine.")
    await _open(library)
    with use_library(library):
        path, manifest = await library_service.export_library()
        contents = await library_service.contents()
    return LibraryExport(
        library=library,
        path=str(path),
        bytes=path.stat().st_size,
        files=len(manifest.files),
        contents=LibraryContents(**contents),
    )
