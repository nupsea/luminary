"""Stubs keep the call signature of the service they stand in for.

A stub whose signature drifts raises TypeError at the call site; where the caller
treats that as non-fatal, the test passes without the stubbed step ever running (#101).
"""

import inspect

import pytest
from stubs import MockEmbeddingService, MockEntityExtractor

from app.services.embedder import EmbeddingService
from app.services.ner import EntityExtractor


@pytest.mark.parametrize(
    ("stub", "real"),
    [
        (MockEntityExtractor.extract, EntityExtractor.extract),
        (MockEmbeddingService.encode, EmbeddingService.encode),
    ],
)
def test_stub_accepts_every_parameter_the_service_takes(stub, real):
    assert list(inspect.signature(stub).parameters) == list(inspect.signature(real).parameters)
