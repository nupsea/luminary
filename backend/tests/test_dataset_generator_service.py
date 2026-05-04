"""Unit tests for generated golden dataset service helpers (S219)."""

import pytest

from app.models import ChunkModel
from app.services.dataset_generator_service import _quality_filter, target_count_for


def test_target_count_size_mapping_and_cap():
    assert target_count_for("small", 1) == 10
    assert target_count_for("medium", 2) == 100
    assert target_count_for("large", 10) == 1000

    with pytest.raises(ValueError, match="invalid dataset size"):
        target_count_for("tiny", 1)


def test_quality_filter_requires_supported_hint_and_nontrivial_answer(monkeypatch):
    chunk = ChunkModel(
        id="chunk-1",
        document_id="doc-1",
        text="Photosynthesis converts light energy into chemical energy in plants.",
        chunk_index=0,
    )

    monkeypatch.setattr(
        "app.services.dataset_generator_service._dedupe_by_embedding",
        lambda candidates: candidates,
    )

    accepted = _quality_filter(
        [
            {
                "question": "What does photosynthesis convert?",
                "answer": "Light energy into chemical energy.",
                "context_hint": "converts light energy into chemical energy",
            },
            {
                "question": "Unsupported?",
                "answer": "Something plausible but not grounded.",
                "context_hint": "not present in the source",
            },
            {
                "question": "Too short?",
                "answer": "yes",
                "context_hint": "light energy",
            },
        ],
        chunk,
    )

    assert accepted == [
        {
            "question": "What does photosynthesis convert?",
            "ground_truth_answer": "Light energy into chemical energy.",
            "context_hint": "converts light energy into chemical energy",
        }
    ]
