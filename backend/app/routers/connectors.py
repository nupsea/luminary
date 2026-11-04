"""Installed connectors: list, connect, preview and ingest, each drawn from what the connector
described itself as (`describe`), so a new connector needs no route or screen of its own."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Response

from app.schemas.connectors import (
    CatalogueItem,
    CatalogueResponse,
    ConnectorIngestRequest,
    ConnectorItem,
    ConnectorListResponse,
    ConnectorPreview,
    ConnectorStatus,
    ConnectorUrlRequest,
    ConnectRequest,
)
from app.services import connector_catalogue as catalogue
from app.services import connectors as svc
from app.services.connector_runner import InstalledConnector, call
from app.streaming import StreamingResponse
from app.workflows.connector_ingestion import start_claimed

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.get("", response_model=ConnectorListResponse)
async def list_connectors() -> ConnectorListResponse:
    return ConnectorListResponse(connectors=[_item(c) for c in svc.installed_connectors()])


# Literal segments before `/{name}/...`.
@router.get("/catalogue", response_model=CatalogueResponse)
async def list_catalogue() -> CatalogueResponse:
    versions = {c.name: c.description.get("version") for c in svc.installed_connectors()}
    return CatalogueResponse(
        connectors=[
            CatalogueItem(
                name=e.name, label=e.label, version=e.version, summary=e.summary,
                licence=e.licence, terms={"statement": e.terms_statement, "url": e.terms_url},
                repository=e.repository, size_bytes=e.size_bytes,
                installed_version=versions.get(e.name),
            )
            for e in catalogue.catalogue_entries()
        ]
    )  # fmt: skip


@router.post("/catalogue/{name}/install")
async def install_from_catalogue(name: str) -> StreamingResponse:
    """Server-sent events, as a component install streams: `downloading`, then `ready` or
    `failed`. Only ever on the user's action."""
    catalogue.get_entry(name)

    async def _stream():
        try:
            async for event in catalogue.install_entry(name):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            logger.exception("catalogue install of %s failed", name)
            yield f"data: {json.dumps({'state': 'failed', 'detail': str(exc)})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.delete("/{name}", status_code=204)
async def uninstall_connector(name: str) -> Response:
    svc.uninstall(name)
    return Response(status_code=204)


@router.get("/{name}/status", response_model=ConnectorStatus)
async def connector_status(name: str) -> ConnectorStatus:
    connector = svc.get_connector(name)
    if not svc.is_connected(connector):
        return ConnectorStatus(connected=False, valid=False)
    account = await call(connector, "check", credentials=svc.load_credentials(name))
    return ConnectorStatus(
        connected=True,
        valid=bool(account.get("valid")),
        account=account.get("account"),
        error=None if account.get("valid") else account.get("message"),
    )


@router.put("/{name}/credentials", response_model=ConnectorStatus)
async def connect_connector(name: str, body: ConnectRequest) -> ConnectorStatus:
    account = await svc.connect(svc.get_connector(name), body.values)
    return ConnectorStatus(connected=True, valid=True, account=account.get("account"))


@router.delete("/{name}/credentials", status_code=204)
async def disconnect_connector(name: str) -> Response:
    svc.get_connector(name)
    svc.delete_credentials(name)
    return Response(status_code=204)


@router.post("/{name}/preview", response_model=ConnectorPreview)
async def preview_link(name: str, body: ConnectorUrlRequest) -> ConnectorPreview:
    connector = svc.claiming(name, body.url)
    credentials = svc.require_credentials(connector)
    data = await call(connector, "preview", input={"url": body.url}, credentials=credentials)
    return ConnectorPreview.model_validate(data)


@router.post("/{name}/ingest")
async def ingest_link(name: str, body: ConnectorIngestRequest) -> dict:
    return await start_claimed(svc.claiming(name, body.url), body.url, body.input)


def _item(connector: InstalledConnector) -> ConnectorItem:
    d = connector.description
    return ConnectorItem(
        name=connector.name,
        label=svc.label_of(connector),
        version=d.get("version", ""),
        licence=d.get("licence", ""),
        terms=d["terms"],
        url_prefixes=d.get("url_prefixes") or [],
        inputs=d.get("inputs") or [],
        credentials=d.get("credentials") or [],
        preview=bool(d.get("preview")),
        connected=svc.is_connected(connector),
    )
