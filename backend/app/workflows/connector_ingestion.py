"""Ingest a link an installed connector claims: fetch it into a bundle, store it, ingest it.

Runs as the document's ingestion job, so the request returns at once and the fetch shows as
the `downloading` stage, as a YouTube download does.
"""

import asyncio
import logging
import shutil
import uuid
from typing import Any

from app.database import get_session_factory
from app.models import DocumentModel
from app.services import ingestion_progress
from app.services.component_advice import ComponentsMissing, components_missing_detail
from app.services.connector_runner import ConnectorFailed, InstalledConnector, call
from app.services.connectors import (
    label_of,
    load_credentials,
    missing_components,
    require_credentials,
    tool_paths,
)
from app.services.ingestion_jobs import get_ingestion_jobs
from app.services.source_bundle import BUNDLE_SUFFIX, BundleRefused
from app.storage import library_root
from app.workflows.bundle_ingestion import store_document_bundle
from app.workflows.ingestion import run_ingestion

logger = logging.getLogger(__name__)

FETCH_SUFFIX = ".fetch"
# A text bundle is a book of chapters, so it opens in the book view, whose routes read a
# stored bundle as they read an EPUB (`epub_service`).
TEXT_BUNDLE_FORMAT = "epub"


async def start_claimed(
    connector: InstalledConnector, url: str, choices: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A claimed link's checks, then its ingestion: a required sign-in, then the components
    its media and tools need. Each refuses before a document exists."""
    require_credentials(connector)
    if required := await missing_components(connector):
        raise ComponentsMissing(components_missing_detail(required, label_of(connector)))
    return await start_connector_ingestion(url, connector, choices)


async def start_connector_ingestion(
    url: str, connector: InstalledConnector, choices: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Create the document at once and fetch in its job. `choices` are the user's picks from
    the connector's preview and inputs; they reach `fetch` beside the URL."""
    doc_id = str(uuid.uuid4())
    raw = library_root() / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    async with get_session_factory()() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title=url,
                format=TEXT_BUNDLE_FORMAT,
                word_count=0,
                page_count=0,
                file_path=str(raw / f"{doc_id}{BUNDLE_SUFFIX}"),
                file_hash=None,
                stage="downloading",
                source_url=url,
            )
        )
        await session.commit()
    get_ingestion_jobs().launch(doc_id, fetch_and_ingest(doc_id, url, connector, choices or {}))
    logger.info(
        "Connector ingestion started", extra={"doc_id": doc_id, "connector": connector.name}
    )
    return {"document_id": doc_id, "status": "processing"}


async def _fail(doc_id: str, message: str) -> None:
    async with get_session_factory()() as session:
        doc = await session.get(DocumentModel, doc_id)
        if doc:
            doc.stage = "error"
            doc.error_message = message
            await session.commit()


async def fetch_and_ingest(
    doc_id: str, url: str, connector: InstalledConnector, choices: dict[str, Any] | None = None
) -> None:
    # The connector writes here, the importer copies from here; never into the library itself.
    fetch_dir = library_root() / "raw" / f"{doc_id}{FETCH_SUFFIX}"
    try:
        await call(
            connector,
            "fetch",
            input={**(choices or {}), "url": url, "tools": tool_paths(connector)},
            credentials=load_credentials(connector.name),
            dest=str(fetch_dir),
            on_progress=lambda f, _s: ingestion_progress.report(doc_id, "downloading", f),
        )
        dest, fmt = await store_document_bundle(doc_id, fetch_dir)
    except (ConnectorFailed, BundleRefused) as exc:
        logger.warning("Connector %s could not fetch %s: %s", connector.name, url, exc.detail)
        await _fail(doc_id, f"{connector.name}: {exc.detail}")
        return
    except Exception as exc:  # a document left at `downloading` would never say why
        logger.exception("Connector %s fetch of %s failed", connector.name, url)
        await _fail(doc_id, f"{connector.name}: {exc}")
        return
    finally:
        ingestion_progress.clear(doc_id)
        await asyncio.to_thread(shutil.rmtree, fetch_dir, True)
    # run_ingestion records its own failures on the document.
    await run_ingestion(doc_id, str(dest), fmt)
