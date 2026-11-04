"""Installed connectors: list, connect, preview and ingest, each drawn from what the connector
described itself as (`describe`), so a new connector needs no route or screen of its own."""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.schemas.connectors import (
    ConnectorIngestRequest,
    ConnectorItem,
    ConnectorListResponse,
    ConnectorPreview,
    ConnectorStatus,
    ConnectorUrlRequest,
    ConnectRequest,
)
from app.services import connectors as svc
from app.services.connector_runner import InstalledConnector, call
from app.workflows.connector_ingestion import start_claimed

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.get("", response_model=ConnectorListResponse)
async def list_connectors() -> ConnectorListResponse:
    return ConnectorListResponse(connectors=[_item(c) for c in svc.installed_connectors()])


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
