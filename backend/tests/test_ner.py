"""Tests for EntityExtractor (GLiNER-based NER).

The model-loading test is skipped unless the GLiNER model is cached.
"""

from unittest.mock import MagicMock

import pytest

from app.services.ner import ENTITY_TYPES, EntityExtractor

FIXTURE_TEXT = (
    "Albert Einstein was born in Ulm, Germany in 1879. "
    "He developed the theory of relativity while working at the Swiss Patent Office in Bern. "
    "In 1921, Einstein received the Nobel Prize in Physics. "
    "His work on quantum mechanics and thermodynamics influenced many scientists, "
    "including Niels Bohr at the University of Copenhagen. "
    "Einstein later emigrated to the United States and joined Princeton University. "
    "His famous equation E=mc² became a cornerstone of modern physics."
)


def _make_chunk(text: str, chunk_id: str = "c1", doc_id: str = "d1") -> dict:
    return {"id": chunk_id, "document_id": doc_id, "text": text}


# ---------------------------------------------------------------------------
# Unit tests with mocked GLiNER model
# ---------------------------------------------------------------------------


@pytest.fixture()
def extractor(tmp_path) -> EntityExtractor:
    return EntityExtractor(data_dir=str(tmp_path))


def test_entity_types_list():
    """ENTITY_TYPES contains the required types."""
    required = {"PERSON", "ORGANIZATION", "PLACE", "CONCEPT", "EVENT", "TECHNOLOGY", "DATE"}
    assert required.issubset(set(ENTITY_TYPES))


def test_extract_returns_list_with_mock(extractor: EntityExtractor):
    """extract() returns entity dicts with required fields."""
    mock_model = MagicMock()
    # batch_predict_entities returns list[list[dict]] — one list per input text
    mock_model.batch_predict_entities.return_value = [
        [
            {"text": "Albert Einstein", "label": "PERSON"},
            {"text": "Germany", "label": "PLACE"},
        ]
    ]
    extractor._model = mock_model

    chunks = [_make_chunk(FIXTURE_TEXT)]
    result = extractor.extract(chunks)

    assert len(result) == 2
    for ent in result:
        assert "id" in ent
        assert "name" in ent
        assert "type" in ent
        assert "chunk_id" in ent
        assert "document_id" in ent


def test_extract_normalizes_name_to_lowercase(extractor: EntityExtractor):
    mock_model = MagicMock()
    mock_model.batch_predict_entities.return_value = [
        [{"text": "Albert Einstein", "label": "PERSON"}]
    ]
    extractor._model = mock_model

    chunks = [_make_chunk("Some text")]
    result = extractor.extract(chunks)

    assert result[0]["name"] == "albert einstein"


def test_extract_generates_deterministic_id(extractor: EntityExtractor):
    """Same entity name + document_id produces the same UUID."""
    mock_model = MagicMock()
    mock_model.batch_predict_entities.return_value = [
        [{"text": "Curie", "label": "PERSON"}]
    ]
    extractor._model = mock_model

    chunks = [_make_chunk("Text", chunk_id="c1", doc_id="d1")]
    result1 = extractor.extract(chunks)
    result2 = extractor.extract(chunks)

    assert result1[0]["id"] == result2[0]["id"]


def test_extract_skips_empty_chunks(extractor: EntityExtractor):
    mock_model = MagicMock()
    mock_model.batch_predict_entities.return_value = []
    extractor._model = mock_model

    chunks = [_make_chunk("   ")]
    result = extractor.extract(chunks)

    assert result == []
    mock_model.batch_predict_entities.assert_not_called()


def test_extract_assigns_chunk_and_doc_ids(extractor: EntityExtractor):
    mock_model = MagicMock()
    mock_model.batch_predict_entities.return_value = [
        [{"text": "Berlin", "label": "PLACE"}]
    ]
    extractor._model = mock_model

    chunks = [_make_chunk("Berlin text", chunk_id="chunk-42", doc_id="doc-99")]
    result = extractor.extract(chunks)

    assert result[0]["chunk_id"] == "chunk-42"
    assert result[0]["document_id"] == "doc-99"


def test_extract_strips_context_header(extractor: EntityExtractor):
    """NER should ignore [Book > Section] headers injected for search."""
    mock_model = MagicMock()
    # If the header is NOT stripped, the mock will receive the full text
    # with the header. We'll check the call arguments.
    mock_model.batch_predict_entities.return_value = [
        [{"text": "Berlin", "label": "PLACE"}]
    ]
    extractor._model = mock_model

    header = "[The Great Gatsby > Chapter 1] "
    content = "Nick Carraway moved to West Egg."
    chunks = [_make_chunk(header + content)]

    extractor.extract(chunks)

    # Check the first argument of the first call to batch_predict_entities
    called_texts = mock_model.batch_predict_entities.call_args[0][0]
    assert called_texts[0] == content
    assert header not in called_texts[0]


# ---------------------------------------------------------------------------
# Integration test (skipped if model not cached)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not __import__("os").path.exists(
        __import__("os").path.expanduser("~/.luminary/models/gliner")
    ),
    reason="GLiNER model not cached in DATA_DIR/models/gliner — skipping integration test",
)
def test_extract_from_fixture_paragraph(tmp_path):
    """With the real GLiNER model, extract at least 2 entities from fixture text."""
    import os

    # Use the real cache dir
    extractor = EntityExtractor(data_dir=os.path.expanduser("~/.luminary"))
    chunks = [_make_chunk(FIXTURE_TEXT)]
    result = extractor.extract(chunks)

    assert len(result) >= 2
    for ent in result:
        assert "name" in ent
        assert "type" in ent
        assert ent["type"] in ENTITY_TYPES
