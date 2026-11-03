"""Hand a connector's bundle to the ingestion pipeline as a document's stored source."""

import asyncio
from pathlib import Path

from app.database import get_session_factory
from app.exceptions import NotFound
from app.repos.document_repo import DocumentRepo
from app.services.source_bundle import BUNDLE_SUFFIX, store_bundle
from app.storage import library_root
from app.workflows.ingestion import run_ingestion


async def ingest_bundle(doc_id: str, source: Path) -> None:
    """Store the bundle at `source` as the document's source, then ingest it.

    The document row must exist. Raises `BundleRefused` before anything is stored when the
    bundle fails a check; the caller records that on the document, as for a failed download.
    Re-import and resume read the stored copy, so the connector never runs again.
    """
    async with get_session_factory()() as session:
        doc = await DocumentRepo(session).get(doc_id)
        if doc is None:
            raise NotFound(f"Document not found: {doc_id}")
        fmt = doc.format

    dest = library_root() / "raw" / f"{doc_id}{BUNDLE_SUFFIX}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(store_bundle, source, dest)
    async with get_session_factory()() as session:
        await DocumentRepo(session).update_fields(doc_id, file_path=str(dest))
        await session.commit()
    # run_ingestion records its own failures on the document.
    await run_ingestion(doc_id, str(dest), fmt)
