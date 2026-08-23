"""Every LanceDB table in the shared embedding space declares the same dimension.

I-9: notes, chunks and concepts are written by one embedder (bge-small-en-v1.5,
384-dim) into one space, so a note vector is directly comparable to a chunk
vector. A table declaring a different dimension is a bug.

`note_vectors_v2` declared 1024. It had been that way long enough that a 61-note
library held zero note vectors: a 384-float list cannot be cast into a 1024
fixed-size list, so every `upsert_note_vector` raised, and `embed_and_store_note`
caught it, logged "non-fatal" and returned. Semantic note search had nothing to
search and said so by returning no results, which is indistinguishable from a
library with no matching notes.

The dimension guard in `_get_or_create_note_table` could not catch it: it
compares the table against `NOTE_VECTOR_DIM`, and both were 1024. A constant is
not a check when the constant is the thing that is wrong -- so this asserts
against the embedder itself.
"""

import pyarrow as pa
import pytest

from app.services.vector_store import (
    CONCEPT_SCHEMA,
    EMBEDDING_DIM,
    IMAGE_SCHEMA,
    NOTE_SCHEMA,
    SCHEMA,
)

_TABLES = [
    ("chunk_vectors_v3", SCHEMA),
    ("note_vectors_v2", NOTE_SCHEMA),
    ("concept_vectors_v1", CONCEPT_SCHEMA),
    ("image_vectors_v1", IMAGE_SCHEMA),
]


@pytest.mark.parametrize(("name", "schema"), _TABLES)
def test_every_table_declares_the_shared_dimension(name: str, schema: pa.Schema) -> None:
    field = schema.field("vector")
    assert field.type.list_size == EMBEDDING_DIM, (
        f"{name} declares {field.type.list_size}-dim vectors; notes, chunks and "
        f"concepts share one {EMBEDDING_DIM}-dim space (I-9). A table that "
        f"disagrees rejects every write from the deployed embedder."
    )


def test_the_shared_dimension_is_the_deployed_embedder_s() -> None:
    """The number is a property of the model, not a choice. Asserting it against
    the embedder is what makes the constant checkable rather than merely stated."""
    from app.services.embedder import get_embedding_service

    produced = len(get_embedding_service().encode(["dimension probe"])[0])
    assert produced == EMBEDDING_DIM, (
        f"the deployed embedder produces {produced}-dim vectors but the tables "
        f"declare {EMBEDDING_DIM}; every write into that space will be rejected"
    )
