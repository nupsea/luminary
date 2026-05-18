"""Pure helpers extracted from `app/routers/flashcards.py`.

The `flashcards.py` router file already imports several helpers from the
`flashcard*` services (FlashcardService, _delete_flashcard_fts, etc.),
so this module is named `flashcards_router_service` to avoid a name
clash with the existing `flashcard_*` service modules.
"""

from __future__ import annotations

import csv
import io

from app.models import FlashcardModel
from app.schemas.flashcards import FlashcardResponse


def to_response(card: FlashcardModel, section_id: str | None = None) -> FlashcardResponse:
    return FlashcardResponse(
        id=card.id,
        document_id=card.document_id,
        chunk_id=card.chunk_id,
        source=card.source if card.source else "document",
        question=card.question,
        answer=card.answer,
        source_excerpt=card.source_excerpt,
        difficulty=card.difficulty,
        is_user_edited=card.is_user_edited,
        fsrs_state=card.fsrs_state,
        fsrs_stability=card.fsrs_stability,
        fsrs_difficulty=card.fsrs_difficulty,
        due_date=card.due_date,
        reps=card.reps,
        lapses=card.lapses,
        created_at=card.created_at,
        flashcard_type=getattr(card, "flashcard_type", None),
        bloom_level=getattr(card, "bloom_level", None),
        section_id=section_id,
        cloze_text=getattr(card, "cloze_text", None),
        chunk_classification=getattr(card, "chunk_classification", None),
        section_heading=getattr(card, "section_heading", None),
    )


def cards_to_csv(cards: list[FlashcardModel], document_title: str) -> str:
    """Render flashcards as a CSV string.

    Pure function — no I/O. All inputs are explicit parameters.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["question", "answer", "source_excerpt", "document_title"])
    for card in cards:
        writer.writerow([card.question, card.answer, card.source_excerpt, document_title])
    return output.getvalue()
