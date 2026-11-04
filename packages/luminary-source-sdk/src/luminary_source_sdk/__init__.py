"""Write connectors that fetch content into Luminary source bundles.

A connector subclasses `Connector`, names the subclass in its `pyproject.toml`:

    [project.entry-points."luminary.connectors"]
    my-source = "my_package.connector:MySource"

and writes each fetch through the `BundleWriter` it is handed. Luminary runs it as its own
process (`luminary_source_sdk.serve`), one request per run.
"""

from luminary_source_sdk.bundle import BundleError, BundleWriter
from luminary_source_sdk.connector import Connector, ConnectorError, Report
from luminary_source_sdk.protocol import PROTOCOL_VERSION, Description, Field, Terms

__all__ = [
    "PROTOCOL_VERSION",
    "BundleError",
    "BundleWriter",
    "Connector",
    "ConnectorError",
    "Description",
    "Field",
    "Report",
    "Terms",
]
