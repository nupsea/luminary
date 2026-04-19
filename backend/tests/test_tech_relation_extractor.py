"""Tests for tech_relation_extractor: pattern-based tech relationship extraction."""

from app.services.tech_relation_extractor import extract_tech_relations


def _chunk(text: str, chunk_id: str = "c1", doc_id: str = "d1") -> dict:
    return {"id": chunk_id, "document_id": doc_id, "text": text}


# ---------------------------------------------------------------------------
# AC2: 'numpy implements ndarray' -> IMPLEMENTS edge
# ---------------------------------------------------------------------------


def test_implements_pattern_ac2():
    """AC2: 'numpy implements ndarray using a contiguous memory block' -> IMPLEMENTS."""
    chunks = [_chunk("numpy implements ndarray using a contiguous memory block")]
    known = {"numpy", "ndarray"}
    result = extract_tech_relations(chunks, known)
    assert ("numpy", "ndarray", "IMPLEMENTS") in result


def test_implements_case_insensitive():
    chunks = [_chunk("SQLAlchemy Implements ORM patterns efficiently")]
    known = {"sqlalchemy", "orm"}
    result = extract_tech_relations(chunks, known)
    assert ("sqlalchemy", "orm", "IMPLEMENTS") in result


# ---------------------------------------------------------------------------
# EXTENDS pattern
# ---------------------------------------------------------------------------


def test_extends_pattern():
    chunks = [_chunk("UserModel extends BaseModel to add authentication fields")]
    known = {"usermodel", "basemodel"}
    result = extract_tech_relations(chunks, known)
    assert ("usermodel", "basemodel", "EXTENDS") in result


# ---------------------------------------------------------------------------
# USES pattern
# ---------------------------------------------------------------------------


def test_uses_pattern():
    chunks = [_chunk("FastAPI uses Pydantic for request validation")]
    known = {"fastapi", "pydantic"}
    result = extract_tech_relations(chunks, known)
    assert ("fastapi", "pydantic", "USES") in result


# ---------------------------------------------------------------------------
# DEPENDS_ON pattern — 'requires' and 'depends on' sub-patterns
# ---------------------------------------------------------------------------


def test_depends_on_requires_pattern():
    chunks = [_chunk("sqlalchemy requires psycopg2 for PostgreSQL connectivity")]
    known = {"sqlalchemy", "psycopg2"}
    result = extract_tech_relations(chunks, known)
    assert ("sqlalchemy", "psycopg2", "DEPENDS_ON") in result


def test_depends_on_depends_pattern():
    chunks = [_chunk("celery depends on redis for task queuing")]
    known = {"celery", "redis"}
    result = extract_tech_relations(chunks, known)
    assert ("celery", "redis", "DEPENDS_ON") in result


# ---------------------------------------------------------------------------
# REPLACES pattern
# ---------------------------------------------------------------------------


def test_replaces_pattern():
    chunks = [_chunk("asyncio replaces threading for concurrent Python code")]
    known = {"asyncio", "threading"}
    result = extract_tech_relations(chunks, known)
    assert ("asyncio", "threading", "REPLACES") in result


# ---------------------------------------------------------------------------
# IMPORT pattern -> USES edge
# ---------------------------------------------------------------------------


def test_import_pattern_creates_uses():
    """'import sqlalchemy' with another known entity creates USES edge."""
    text = "import sqlalchemy\nsqlalchemy connects to postgres"
    chunks = [_chunk(text)]
    known = {"sqlalchemy", "postgres"}
    result = extract_tech_relations(chunks, known)
    labels = [r[2] for r in result]
    assert "USES" in labels


def test_from_import_pattern():
    """'from numpy import ndarray' with both entities known."""
    text = "from numpy import ndarray\nnumpy provides ndarray"
    chunks = [_chunk(text)]
    known = {"numpy", "ndarray"}
    result = extract_tech_relations(chunks, known)
    # numpy is imported, ndarray is a co-occurring entity -> USES edge expected
    assert any(r[2] == "USES" for r in result)


# ---------------------------------------------------------------------------
# Guard: no edge when one entity is unknown
# ---------------------------------------------------------------------------


def test_no_relation_for_unknown_entity():
    """No edge when target entity is not in known_names."""
    chunks = [_chunk("numpy implements ndarray")]
    known = {"numpy"}  # ndarray not confirmed by GLiNER
    result = extract_tech_relations(chunks, known)
    assert result == []


def test_no_relation_empty_known():
    chunks = [_chunk("numpy implements ndarray")]
    result = extract_tech_relations(chunks, set())
    assert result == []


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_duplicate_relations_deduplicated():
    """Same relation appearing in two chunks is only returned once."""
    chunks = [
        _chunk("numpy implements ndarray efficiently", chunk_id="c1"),
        _chunk("numpy implements ndarray in C", chunk_id="c2"),
    ]
    known = {"numpy", "ndarray"}
    result = extract_tech_relations(chunks, known)
    count = sum(1 for r in result if r == ("numpy", "ndarray", "IMPLEMENTS"))
    assert count == 1


# ---------------------------------------------------------------------------
# Edge case: empty chunks
# ---------------------------------------------------------------------------


def test_empty_chunks():
    result = extract_tech_relations([], {"numpy", "ndarray"})
    assert result == []


def test_chunk_with_no_text():
    result = extract_tech_relations([{"id": "c1", "document_id": "d1"}], {"numpy"})
    assert result == []
