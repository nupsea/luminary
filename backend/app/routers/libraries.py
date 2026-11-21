"""The libraries on this machine: list, create, name, switch, remove, export and import.

Routes: GET /libraries, POST /libraries, PUT /libraries/active, GET /libraries/destinations,
POST /libraries/import, POST /libraries/import-from-folder, POST /libraries/reveal,
PATCH /libraries/{library}, DELETE /libraries/{library}, POST /libraries/{library}/export

The app's own, like devices: a paired device works in the library it paired into and may
not see, switch or copy the others.
"""

import asyncio

from fastapi import APIRouter, File, Form, Response, UploadFile

from app.library import DEFAULT_LIBRARY, use_library
from app.runtime.library_work import remove_library, serve_library
from app.schemas.libraries import (
    ArchiveItem,
    ArchiveRef,
    DestinationItem,
    DestinationList,
    ExportRequest,
    ImportFromFolder,
    LibraryContents,
    LibraryCreate,
    LibraryExport,
    LibraryImport,
    LibraryItem,
    LibraryList,
    LibraryName,
    LibraryProfile,
    LibraryRemoved,
)
from app.services import libraries as library_service
from app.services import sync_folders
from app.services.library_snapshot import Manifest

# No device scope: spaces are managed from Luminary itself (I-79).
router = APIRouter(prefix="/libraries", tags=["libraries"])


async def _open(library: str) -> None:
    if library != DEFAULT_LIBRARY:  # startup serves the default
        await serve_library(library)


async def _list() -> LibraryList:
    items = await library_service.list_libraries()
    return LibraryList(
        active=library_service.active_library(),
        libraries=[
            LibraryItem(
                id=i.id,
                active=i.active,
                bytes=i.bytes,
                name=i.name,
                color=i.color,
                contents=None if i.contents is None else LibraryContents(**i.contents),
            )
            for i in items
        ],
    )


async def _imported(library: str, manifest: Manifest, activate: bool) -> LibraryImport:
    await _open(library)
    with use_library(library):
        contents = await library_service.contents()
    profile = await library_service.settle_imported_name(library)
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
        **profile,
    )


@router.get("", response_model=LibraryList)
async def list_libraries() -> LibraryList:
    return await _list()


@router.post("", response_model=LibraryList, status_code=201)
async def create_library(req: LibraryCreate) -> LibraryList:
    library = library_service.library_id(req.library)
    library_service.check_new_library(library)
    await _open(library)
    with use_library(library):
        await library_service.write_profile(name=req.name, color=req.color)
    return await _list()


@router.put("/active", response_model=LibraryList)
async def switch_library(req: LibraryName) -> LibraryList:
    library = library_service.require_library(req.library)
    # Opened and migrated first: a library that cannot open is never switched to.
    await _open(library)
    library_service.set_active_library(library)
    return await _list()


@router.get("/destinations", response_model=DestinationList)
async def list_destinations() -> DestinationList:
    def _scan() -> list[DestinationItem]:
        return [
            DestinationItem(
                id=d.id,
                kind=d.kind,
                name=d.name,
                path=str(d.folder),
                archives=[
                    ArchiveItem(name=a.name, bytes=a.bytes, modified=a.modified)
                    for a in sync_folders.archives(d)
                ],
            )
            for d in sync_folders.destinations()
        ]

    return DestinationList(destinations=await asyncio.to_thread(_scan))


@router.post("/import", response_model=LibraryImport, status_code=201)
async def import_library(
    file: UploadFile = File(...),
    library: str = Form(...),
    activate: bool = Form(False),
) -> LibraryImport:
    library = library_service.library_id(library)
    manifest = await library_service.import_archive(file.file, library)
    return await _imported(library, manifest, activate)


@router.post("/import-from-folder", response_model=LibraryImport, status_code=201)
async def import_from_folder(req: ImportFromFolder) -> LibraryImport:
    library = library_service.library_id(req.library)
    dest = await asyncio.to_thread(sync_folders.destination, req.destination)
    archive = await asyncio.to_thread(sync_folders.archive_path, dest, req.name)
    manifest = await library_service.import_from(archive, library)
    return await _imported(library, manifest, req.activate)


@router.post("/reveal", status_code=204)
async def reveal_archive(req: ArchiveRef) -> Response:
    dest = await asyncio.to_thread(sync_folders.destination, req.destination)
    archive = await asyncio.to_thread(sync_folders.archive_path, dest, req.name)
    await asyncio.to_thread(sync_folders.reveal, archive)
    return Response(status_code=204)


@router.patch("/{library}", response_model=LibraryList)
async def update_library(library: str, req: LibraryProfile) -> LibraryList:
    library = library_service.require_library(library)
    with use_library(library):
        await library_service.write_profile(name=req.name, color=req.color)
    return await _list()


@router.delete("/{library}", response_model=LibraryRemoved)
async def delete_library(library: str) -> LibraryRemoved:
    library = library_service.require_library(library)
    return LibraryRemoved(library=library, removed_now=await remove_library(library))


@router.post("/{library}/export", response_model=LibraryExport)
async def export_library(library: str, req: ExportRequest | None = None) -> LibraryExport:
    library = library_service.require_library(library)
    dest = await asyncio.to_thread(sync_folders.destination, (req or ExportRequest()).destination)
    await _open(library)
    with use_library(library):
        path, manifest = await library_service.export_library(dest)
        contents = await library_service.contents()
    return LibraryExport(
        library=library,
        destination=dest.id,
        destination_name=dest.name,
        path=str(path),
        name=path.name,
        bytes=path.stat().st_size,
        files=len(manifest.files),
        contents=LibraryContents(**contents),
    )
