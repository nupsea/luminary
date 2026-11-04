"""Installed connectors as the settings card, the connect form and the upload dialog read them."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConnectorField(BaseModel):
    name: str
    label: str
    secret: bool = False
    required: bool = True
    help: str = ""
    multiline: bool = False


class ConnectorTerms(BaseModel):
    statement: str
    url: str


class ConnectorItem(BaseModel):
    """What the connector described itself as, and whether it holds a sign-in."""

    name: str
    label: str
    version: str
    licence: str
    terms: ConnectorTerms
    url_prefixes: list[str]
    inputs: list[ConnectorField]
    credentials: list[ConnectorField]
    preview: bool
    connected: bool


class ConnectorListResponse(BaseModel):
    connectors: list[ConnectorItem]


class ConnectorStatus(BaseModel):
    """`connected` is a stored sign-in; `valid` is the connector's own check of it."""

    connected: bool
    valid: bool
    account: str | None = None
    error: str | None = None


class ConnectRequest(BaseModel):
    values: dict[str, Any] = Field(..., description="Credential field name to its value")


class ConnectorUrlRequest(BaseModel):
    url: str = Field(..., max_length=2048)


class ConnectorOption(BaseModel):
    value: str
    label: str
    detail: str = ""


class ConnectorChoice(BaseModel):
    field: str
    label: str
    options: list[ConnectorOption]
    multiple: bool = False
    default: list[str] = []


class ConnectorPreview(BaseModel):
    title: str
    detail: str = ""
    choices: list[ConnectorChoice] = []


class ConnectorIngestRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    input: dict[str, Any] = Field(
        default_factory=dict,
        description="Values for the connector's inputs and preview choices, by field name",
    )


class CatalogueItem(BaseModel):
    """A connector the app can install, shown with its licence and source terms before the
    install starts. `installed_version` is what this machine has, if any."""

    name: str
    label: str
    version: str
    summary: str
    licence: str
    terms: ConnectorTerms
    repository: str
    size_bytes: int
    installed_version: str | None = None


class CatalogueResponse(BaseModel):
    connectors: list[CatalogueItem]
