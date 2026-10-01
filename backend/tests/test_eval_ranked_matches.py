"""Eval runners read /search in the retriever's order, never by score."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from evals.lib.search import ranked_matches  # noqa: E402


def _body():
    return {
        "results": [
            {
                "document_id": "a",
                "matches": [
                    {"text": "a1", "global_rank": 1, "relevance_score": -9.0},
                    {"text": "a2", "global_rank": 4, "relevance_score": -1.0},
                ],
            },
            {
                "document_id": "b",
                "matches": [
                    {"text": "b1", "global_rank": 2, "relevance_score": -0.5},
                ],
            },
        ]
    }


def test_orders_across_groups_by_global_rank():
    assert [m["text"] for m in ranked_matches(_body())] == ["a1", "b1", "a2"]


def test_tags_each_match_with_its_document():
    assert [m["_doc_id"] for m in ranked_matches(_body())] == ["a", "b", "a"]


def test_filters_to_one_document():
    assert [m["text"] for m in ranked_matches(_body(), "a")] == ["a1", "a2"]


def test_a_match_without_a_rank_keeps_its_grouped_position_last():
    body = {
        "results": [
            {"document_id": "a", "matches": [{"text": "x"}, {"text": "y", "global_rank": 1}]}
        ]
    }
    assert [m["text"] for m in ranked_matches(body)] == ["y", "x"]
