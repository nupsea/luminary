"""Unit tests for generated golden dataset service helpers (S219)."""

import pytest

from app.services.dataset_generator_service import target_count_for
from app.services.golden_quality import quality_filter


def test_target_count_size_mapping_and_cap():
    assert target_count_for("small", 1) == 10
    assert target_count_for("medium", 2) == 100
    assert target_count_for("large", 10) == 1000

    with pytest.raises(ValueError, match="invalid dataset size"):
        target_count_for("tiny", 1)


def test_quality_filter_requires_supported_hint_and_nontrivial_answer(monkeypatch):
    source_text = "Photosynthesis converts light energy into chemical energy in plants."

    monkeypatch.setattr(
        "app.services.golden_quality.dedupe_by_embedding",
        lambda candidates: candidates,
    )

    accepted = quality_filter(
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
        source_text,
    )

    assert accepted == [
        {
            "question": "What does photosynthesis convert?",
            "ground_truth_answer": "Light energy into chemical energy.",
            "context_hint": "converts light energy into chemical energy",
        }
    ]
