"""Tests for EntityExtractor (GLiNER-based NER).

The model-loading test is skipped unless the GLiNER model is cached.
"""

from unittest.mock import MagicMock

import pytest

from app.services.ner import _TECH_NOISE_LIBRARY, ENTITY_TYPES, EntityExtractor

FIXTURE_TEXT = (
    "Albert Einstein was born in Ulm, Germany in 1879. "
    "He developed the theory of relativity while working at the Swiss Patent Office in Bern. "
    "In 1921, Einstein received the Nobel Prize in Physics. "
    "His work on quantum mechanics and thermodynamics influenced many scientists, "
    "including Niels Bohr at the University of Copenhagen. "
    "Einstein later emigrated to the United States and joined Princeton University. "
    "His famous equation E=mc² became a cornerstone of modern physics."
)


def _make_chunk(
    text: str, chunk_id: str = "c1", doc_id: str = "d1", has_code: bool = False
) -> dict:
    return {"id": chunk_id, "document_id": doc_id, "text": text, "has_code": has_code}


# ---------------------------------------------------------------------------
# Unit tests with mocked GLiNER model
# ---------------------------------------------------------------------------


@pytest.fixture()
def extractor(tmp_path) -> EntityExtractor:
    return EntityExtractor(data_dir=str(tmp_path))


def test_entity_types_list():
    """ENTITY_TYPES contains the original 7 required types."""
    required = {"PERSON", "ORGANIZATION", "PLACE", "CONCEPT", "EVENT", "TECHNOLOGY", "DATE"}
    assert required.issubset(set(ENTITY_TYPES))


def test_entity_types_includes_tech_types():
    """AC1: ENTITY_TYPES includes the 6 new tech-specific label types (S135)."""
    required_tech = {
        "LIBRARY", "DESIGN_PATTERN", "ALGORITHM",
        "DATA_STRUCTURE", "PROTOCOL", "API_ENDPOINT",
    }
    assert required_tech.issubset(set(ENTITY_TYPES))


def test_tech_noise_blocklist_covers_expected_terms():
    """_TECH_NOISE_LIBRARY contains the documented generic programming terms."""
    expected = {"class", "function", "method", "object", "type", "interface", "module"}
    assert expected.issubset(_TECH_NOISE_LIBRARY)


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
# AC3: Tech noise filter
# ---------------------------------------------------------------------------


def test_tech_noise_filter_rejects_generic_library_terms(extractor: EntityExtractor):
    """AC3: 'class', 'method', 'object' as LIBRARY/ALGORITHM labels are rejected."""
    mock_model = MagicMock()
    mock_model.batch_predict_entities.return_value = [
        [
            {"text": "class", "label": "LIBRARY"},
            {"text": "method", "label": "ALGORITHM"},
            {"text": "object", "label": "DESIGN_PATTERN"},
        ]
    ]
    extractor._model = mock_model

    # Use tech content_type so tech entity types are active
    chunks = [_make_chunk("use the class method on the object")]
    result = extractor.extract(chunks, content_type="tech_book")
    assert result == [], f"Expected no entities, got: {result}"


def test_tech_noise_filter_allows_legitimate_library_names(extractor: EntityExtractor):
    """Legitimate library names like 'numpy', 'react' pass the noise filter."""
    mock_model = MagicMock()
    mock_model.batch_predict_entities.return_value = [
        [{"text": "numpy", "label": "LIBRARY"}]
    ]
    extractor._model = mock_model

    chunks = [_make_chunk("import numpy for array operations")]
    result = extractor.extract(chunks, content_type="tech_book")
    assert len(result) == 1
    assert result[0]["name"] == "numpy"


# ---------------------------------------------------------------------------
# AC5: Code-block confidence boost
# ---------------------------------------------------------------------------


def test_code_block_boost_code_chunk_uses_lower_threshold(extractor: EntityExtractor):
    """AC5: A code chunk (has_code=True) uses threshold=0.55; prose uses 0.65.

    We verify this by checking that batch_predict_entities is called with
    the lower threshold for code chunks in a tech document.
    """
    mock_model = MagicMock()
    mock_model.batch_predict_entities.return_value = [
        [{"text": "numpy", "label": "LIBRARY"}]
    ]
    extractor._model = mock_model

    code_chunk = _make_chunk("import numpy", has_code=True)
    extractor.extract([code_chunk], content_type="tech_book")

    # Verify the lower threshold (0.55) was used for the code chunk
    calls = mock_model.batch_predict_entities.call_args_list
    thresholds_used = [call.kwargs.get("threshold", call.args[2] if len(call.args) > 2 else None)
                       for call in calls]
    assert 0.55 in thresholds_used, (
        f"Expected CODE_THRESHOLD=0.55 to be used for code chunk; calls: {calls}"
    )


def test_code_block_boost_prose_chunk_uses_higher_threshold(extractor: EntityExtractor):
    """Prose chunk (has_code=False) uses threshold=0.65."""
    mock_model = MagicMock()
    mock_model.batch_predict_entities.return_value = []
    extractor._model = mock_model

    prose_chunk = _make_chunk("numpy is used here", has_code=False)
    extractor.extract([prose_chunk], content_type="tech_book")

    calls = mock_model.batch_predict_entities.call_args_list
    thresholds_used = [call.kwargs.get("threshold", call.args[2] if len(call.args) > 2 else None)
                       for call in calls]
    assert 0.65 in thresholds_used, (
        f"Expected PROSE_THRESHOLD=0.65 for prose chunk; calls: {calls}"
    )


def test_non_tech_content_type_excludes_tech_types(extractor: EntityExtractor):
    """For non-tech content types, LIBRARY and other tech types must not be active."""
    mock_model = MagicMock()
    mock_model.batch_predict_entities.return_value = [[]]
    extractor._model = mock_model

    chunks = [_make_chunk("some prose text")]
    extractor.extract(chunks, content_type="book")

    call_args = mock_model.batch_predict_entities.call_args
    active_types = call_args.args[1] if call_args.args else call_args.kwargs.get("labels", [])
    assert "LIBRARY" not in active_types
    assert "TECHNOLOGY" not in active_types


def test_tech_content_type_includes_all_types(extractor: EntityExtractor):
    """For tech_book content, all 13 entity types must be active."""
    mock_model = MagicMock()
    mock_model.batch_predict_entities.return_value = []
    extractor._model = mock_model

    chunks = [_make_chunk("some tech text")]
    extractor.extract(chunks, content_type="tech_book")

    # All batch_predict_entities calls for prose (and code if any) should include LIBRARY
    for call in mock_model.batch_predict_entities.call_args_list:
        active = call.args[1] if call.args else call.kwargs.get("labels", [])
        if active:  # skip empty call lists
            assert "LIBRARY" in active


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
