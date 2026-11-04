"""The class a connector subclasses."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from luminary_source_sdk.bundle import BundleWriter
from luminary_source_sdk.protocol import Description

Report = Callable[[float, str], None]


class ConnectorError(Exception):
    """A failure the user can act on. `code` is one of: input, auth, source, internal."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Connector:
    """Subclass it, and name the subclass in the `luminary.connectors` entry point."""

    def describe(self) -> Description:
        raise NotImplementedError

    def preview(self, input: dict[str, Any], credentials: dict[str, Any]) -> dict[str, Any]:
        """What the user confirms before fetching, e.g. a chapter list. Optional."""
        raise ConnectorError("input", "this connector offers no preview")

    def fetch(
        self,
        input: dict[str, Any],
        credentials: dict[str, Any],
        bundle: BundleWriter,
        report: Report,
    ) -> None:
        """Write the whole source into `bundle`, calling `report(fraction, stage)` as it goes."""
        raise NotImplementedError
