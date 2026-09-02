"""LanceDB predicates are built by interpolation, so ids are shape-checked (#95).

LanceDB takes `where`/`filter`/`delete` as SQL strings and offers no parameter
binding, so "bind the ids" is not available here. Shape-checking before quoting
is, and these assert the two properties that matter: nothing but an id this
process generates reaches a predicate, and every id it does generate is accepted.
"""

from __future__ import annotations

import pytest

from app.services.vector_store import eq_predicate, id_predicate, safe_id

DASHED = "02acff68-b6bb-4efa-a5af-d6a8d3d9e465"  # uuid4(): documents, chunks, notes, images
BARE = "005a25379cc44337bedd4a24b8b7364d"  # uuid4().hex: concepts, study events


class TestAcceptsWhatTheProcessGenerates:
    """Both id shapes are real, and refusing either breaks a feature silently.

    `concepts.id` is `uuid.uuid4().hex` -- 32 hex characters, no dashes. A guard
    written against the dashed form alone would make every concept-vector
    predicate match nothing, and `delete_concept_vector` a no-op that logs
    success.
    """

    @pytest.mark.parametrize("value", [DASHED, BARE])
    def test_both_shapes_pass(self, value: str) -> None:
        assert safe_id(value) == value

    def test_a_mixed_batch_keeps_every_id(self) -> None:
        pred = id_predicate("chunk_id", [DASHED, BARE], context="t")
        assert pred is not None
        assert DASHED in pred and BARE in pred


class TestRefusesEverythingElse:
    @pytest.mark.parametrize(
        "value",
        [
            "x' OR '1'='1",
            "'; DROP TABLE chunk_vectors_v3; --",
            "02acff68-b6bb-4efa-a5af-d6a8d3d9e465' OR '1'='1",
            "",
            "not-an-id",
            "005a25379cc44337bedd4a24b8b7364",  # 31 chars
        ],
    )
    def test_rejected(self, value: str) -> None:
        assert safe_id(value) is None
        assert eq_predicate("document_id", value, context="t") is None

    def test_no_survivor_returns_none_not_an_empty_in_list(self) -> None:
        """`IN ()` is a syntax error at best and `WHERE true` at worst.

        Callers treat None as "match nothing"; returning an empty clause here
        would turn a scoped delete into a whole-table one.
        """
        assert id_predicate("chunk_id", ["not-an-id"], context="t") is None
        assert id_predicate("chunk_id", [], context="t") is None

    def test_one_bad_id_does_not_discard_the_good_ones(self) -> None:
        pred = id_predicate("chunk_id", [DASHED, "x' OR '1'='1"], context="t")
        assert pred == f"chunk_id IN ('{DASHED}')"
