"""Pydantic schemas for golden datasets across eval kinds.

GoldenEntry is the base; family subclasses add eval-kind-specific required fields.
"""

from pydantic import BaseModel, field_validator


class GoldenEntry(BaseModel):
    """Base golden entry shared across all eval kinds."""

    question: str
    ground_truth_answer: str = ""
    source_file: str | None = None
    document_id: str | None = None

    model_config = {"extra": "allow"}


class RetrievalGoldenEntry(GoldenEntry):
    """Retrieval golden -- context_hint accepts str or list[str] (S226)."""

    context_hint: list[str] = []

    @field_validator("context_hint", mode="before")
    @classmethod
    def _coerce_hint(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        if isinstance(v, list):
            if len(v) == 0:
                raise ValueError("context_hint list must not be empty")
            for item in v:
                if not isinstance(item, str):
                    raise ValueError(
                        f"context_hint list elements must be str, got {type(item).__name__}"
                    )
            return v
        raise ValueError(f"context_hint must be str or list[str], got {type(v).__name__}")


class SummaryGoldenEntry(GoldenEntry):
    """Summary golden -- expected themes/facts and target length per mode."""

    mode: str = "executive"
    expected_themes: list[str]
    expected_facts: list[str] = []
    target_length_chars: int = 0


class FlashcardGoldenEntry(GoldenEntry):
    """Flashcard golden -- chunk reference and expected facts."""

    chunk_id_or_text: str
    expected_card_count: int = 1
    expected_facts: list[str] = []


class IntentGoldenEntry(GoldenEntry):
    """Intent / chat-graph routing golden -- expected route label."""

    expected_route: str
