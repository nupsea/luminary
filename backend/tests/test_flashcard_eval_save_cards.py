"""Saved eval cards are rows the card_quality judge panel reads (--save-cards)."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals import run_flashcard_eval  # noqa: E402

PANEL_FIELDS = {"card_id", "doc", "chapter", "question", "answer", "passage"}


def test_each_card_carries_its_passage_and_a_stable_id():
    row = {"source_file": "DATA/plays/hamlet.txt", "chunk_id_or_text": "HAMLET. To be."}
    cards = [{"question": "Q1", "answer": "A1"}, {"question": "Q2", "answer": "A2"}]

    rows = run_flashcard_eval.card_rows("flashcards_corpus", 4, row, "doc-id", cards)

    assert [set(r) for r in rows] == [PANEL_FIELDS, PANEL_FIELDS]
    assert [r["card_id"] for r in rows] == ["flashcards_corpus:4:0", "flashcards_corpus:4:1"]
    assert {r["doc"] for r in rows} == {"hamlet"}
    assert {r["passage"] for r in rows} == {"HAMLET. To be."}


def test_a_library_row_is_named_by_its_document_id():
    row = {"source_document_id": "doc-id", "chunk_id_or_text": "text"}

    (saved,) = run_flashcard_eval.card_rows("flashcards", 0, row, "doc-id", [{"question": "Q"}])

    assert saved["doc"] == "doc-id"
    assert saved["answer"] == ""
