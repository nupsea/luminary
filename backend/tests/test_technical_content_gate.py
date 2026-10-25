"""A technical talk must get technical entity types although it is media.

The format keeps a talk media for the player and timestamped chunking; its
subject is the measured `domain`, which the NER gate reads.
"""

from unittest.mock import patch

import pytest

from app.types import DocumentProfile
from app.workflows.ingestion_nodes._shared import detect_technical_transcript, measure_domain


class _FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def generate(self, *args, **kwargs):
        return self.reply


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("technical", True),
        ("Technical.", True),
        ("`general`", False),
        ("General", False),
        ("yes", None),
        ("maybe", None),
    ],
)
async def test_detect_technical_transcript_parses_reply(reply, expected):
    with patch("app.services.llm.get_llm_service", return_value=_FakeLLM(reply)):
        assert await detect_technical_transcript("some transcript text") is expected


@pytest.mark.asyncio
async def test_detect_technical_transcript_is_non_fatal():
    class _Broken:
        async def generate(self, *args, **kwargs):
            raise RuntimeError("ollama down")

    with patch("app.services.llm.get_llm_service", return_value=_Broken()):
        assert await detect_technical_transcript("text") is None


@pytest.mark.asyncio
async def test_empty_transcript_is_undecidable():
    assert await detect_technical_transcript("   ") is None


def test_ner_extract_honours_the_flag():
    from app.services.ner import _TECH_ENTITY_TYPES, ENTITY_TYPES, EntityExtractor

    captured: list[list[str]] = []

    class _FakeModel:
        def batch_predict_entities(self, texts, labels, threshold=0.0, **kwargs):
            captured.append(list(labels))
            return [[] for _ in texts]

        def predict_entities(self, text, labels, threshold=0.0, **kwargs):
            captured.append(list(labels))
            return []

    extractor = EntityExtractor(data_dir="/tmp")
    chunks = [{"id": "c1", "document_id": "d1", "text": "We built it with Automerge."}]

    with patch.object(EntityExtractor, "_load_model", return_value=_FakeModel()):
        extractor.extract(
            chunks, is_technical=DocumentProfile("dialogue", "technical").is_technical
        )
        tech_labels = set(captured[0])
        captured.clear()
        extractor.extract(chunks, is_technical=DocumentProfile("dialogue").is_technical)
        prose_labels = set(captured[0])

    assert "TECHNOLOGY" in tech_labels
    assert _TECH_ENTITY_TYPES & tech_labels
    assert "TECHNOLOGY" not in prose_labels
    assert not (_TECH_ENTITY_TYPES & prose_labels)
    assert tech_labels <= set(ENTITY_TYPES)


@pytest.mark.asyncio
async def test_source_code_is_technical_unasked():
    class _Unreachable:
        async def generate(self, *args, **kwargs):
            raise AssertionError("source code's domain is settled by its shape")

    with patch("app.services.llm.get_llm_service", return_value=_Unreachable()):
        assert await measure_domain("source_code", "def add(a, b):\n    return a + b") is True


@pytest.mark.asyncio
@pytest.mark.parametrize("form", ["reference", "article", "prose"])
async def test_every_other_form_is_asked(form):
    # A reference-shaped work is not technical by shape: the Federalist Papers
    # uploaded as a tech book stayed technical while the type answered for it.
    with patch("app.services.llm.get_llm_service", return_value=_FakeLLM("general")):
        assert await measure_domain(form, "No. 10: The Same Subject Continued") is False
