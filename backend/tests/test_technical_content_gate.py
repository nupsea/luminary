"""A technical talk must get technical entity types despite content_type "audio".

content_type cannot carry technicality for media: "audio"/"video" drive
timestamp-preserving chunking and the player, so the classifier persists a
separate is_technical flag and the NER gate reads that.
"""

from unittest.mock import patch

import pytest

from app.types import TECHNICAL_CONTENT_TYPES, is_technical_content
from app.workflows.ingestion_nodes._shared import detect_technical_transcript


def test_flag_wins_over_content_type():
    assert is_technical_content("audio", True) is True
    assert is_technical_content("tech_book", False) is False


def test_falls_back_to_content_type_when_flag_unset():
    for ct in TECHNICAL_CONTENT_TYPES:
        assert is_technical_content(ct, None) is True
    assert is_technical_content("audio", None) is False
    assert is_technical_content("book", None) is False


class _FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def generate(self, *args, **kwargs):
        return self.reply


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "expected"),
    [("yes", True), ("Yes.", True), ("no", False), ("No", False), ("maybe", None)],
)
async def test_detect_technical_transcript_parses_reply(reply, expected):
    with patch(
        "app.services.llm.get_llm_service", return_value=_FakeLLM(reply)
    ):
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
        extractor.extract(chunks, content_type="audio", is_technical=True)
        tech_labels = set(captured[0])
        captured.clear()
        extractor.extract(chunks, content_type="audio", is_technical=None)
        prose_labels = set(captured[0])

    assert "TECHNOLOGY" in tech_labels
    assert _TECH_ENTITY_TYPES & tech_labels
    assert "TECHNOLOGY" not in prose_labels
    assert not (_TECH_ENTITY_TYPES & prose_labels)
    assert tech_labels <= set(ENTITY_TYPES)
