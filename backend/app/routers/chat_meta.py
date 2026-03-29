"""GET /chat/suggestions and GET /chat/explorations -- DB-only, no LLM, < 200ms."""

import asyncio
import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.database import get_session_factory
from app.models import DocumentModel, SectionModel
from app.services.graph import get_graph_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class SuggestionResponse(BaseModel):
    suggestions: list[str]


class ExplorationSuggestion(BaseModel):
    text: str
    entity_names: list[str]


# ---------------------------------------------------------------------------
# Template-based suggestion generation (pure logic, no LLM)
# ---------------------------------------------------------------------------

_ONBOARDING_SUGGESTIONS = [
    "Upload a document in the Learning tab to get started",
    "Try importing a PDF, EPUB, or text file",
    "You can also paste a YouTube URL to analyze a video",
    "Explore the Knowledge Graph in the Viz tab after uploading",
]


def _book_suggestions(entities: dict[str, list[str]], headings: list[str]) -> list[str]:
    """Generate suggestions for book-type documents."""
    suggestions: list[str] = []
    persons = entities.get("PERSON", [])
    concepts = entities.get("CONCEPT", [])
    places = entities.get("PLACE", [])

    if persons:
        suggestions.append(f"What motivates {persons[0]} throughout the story?")
    if len(persons) >= 2:
        suggestions.append(f"Compare the roles of {persons[0]} and {persons[1]}")
    if concepts:
        suggestions.append(f"How does the theme of {concepts[0].lower()} develop across the text?")
    if places:
        suggestions.append(f"What is the significance of {places[0]} in the narrative?")
    if persons and concepts and len(suggestions) < 4:
        suggestions.append(
            f"How does {persons[0]} relate to the concept of {concepts[0].lower()}?"
        )
    if headings and len(suggestions) < 4:
        suggestions.append(f"Summarize the section on '{headings[0]}'")

    return suggestions[:4]


def _technical_suggestions(entities: dict[str, list[str]], headings: list[str]) -> list[str]:
    """Generate suggestions for technical documents (tech_book, tech_article, code)."""
    suggestions: list[str] = []
    concepts = entities.get("CONCEPT", [])
    technologies = entities.get("TECHNOLOGY", [])
    orgs = entities.get("ORGANIZATION", [])

    items = concepts + technologies
    if len(items) >= 2:
        suggestions.append(f"Explain the tradeoff between {items[0]} and {items[1]}")
    if items:
        suggestions.append(f"How does {items[0]} work in this context?")
    if len(items) >= 2:
        suggestions.append(f"Compare {items[0]} and {items[1]} -- when would you use each?")
    if orgs:
        suggestions.append(f"What role does {orgs[0]} play in this domain?")
    if headings and len(suggestions) < 4:
        suggestions.append(f"Summarize the section on '{headings[0]}'")
    if items and len(suggestions) < 4:
        suggestions.append(f"What are the prerequisites for understanding {items[0]}?")

    return suggestions[:4]


def _video_suggestions(entities: dict[str, list[str]], headings: list[str]) -> list[str]:
    """Generate suggestions for video/audio documents (YouTube, podcasts)."""
    suggestions: list[str] = []
    concepts = entities.get("CONCEPT", [])
    persons = entities.get("PERSON", [])

    if concepts:
        suggestions.append(f"What arguments are made about {concepts[0].lower()}?")
    if persons:
        suggestions.append(f"What evidence does {persons[0]} present?")
    if len(concepts) >= 2:
        suggestions.append(
            f"How does the discussion of {concepts[0].lower()} relate to {concepts[1].lower()}?"
        )
    if headings and len(suggestions) < 4:
        suggestions.append(f"What are the key points from '{headings[0]}'?")
    if concepts and len(suggestions) < 4:
        suggestions.append(f"Summarize the main takeaways about {concepts[0].lower()}")

    return suggestions[:4]


def _generic_suggestions(entities: dict[str, list[str]], headings: list[str]) -> list[str]:
    """Fallback suggestions for unknown document types."""
    suggestions: list[str] = []
    all_names = []
    for names in entities.values():
        all_names.extend(names)

    if all_names:
        suggestions.append(f"What are the main points about {all_names[0]}?")
    if len(all_names) >= 2:
        suggestions.append(f"How is {all_names[0]} related to {all_names[1]}?")
    if headings:
        suggestions.append(f"Summarize the section on '{headings[0]}'")
    suggestions.append("What are the key takeaways from this document?")

    return suggestions[:4]


def _cross_document_suggestions(shared_entities: list[str]) -> list[str]:
    """Generate suggestions for all-scope (no specific document)."""
    suggestions: list[str] = []
    if shared_entities:
        suggestions.append(
            f"Compare how {shared_entities[0]} appears across your documents"
        )
    if len(shared_entities) >= 2:
        suggestions.append(
            f"What connections exist between {shared_entities[0]} and {shared_entities[1]}?"
        )
    if len(shared_entities) >= 3:
        suggestions.append(
            f"Summarize everything you know about {shared_entities[2]}"
        )
    suggestions.append("What are the common themes across my documents?")
    return suggestions[:4]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/suggestions", response_model=SuggestionResponse)
async def get_suggestions(
    document_id: str | None = Query(None, description="Document ID; null for all-scope"),
) -> SuggestionResponse:
    """Return 4 contextual suggestion strings based on document type and entities."""
    if document_id is None:
        # All-scope: cross-document entity overlap (I-2: wrap sync Kuzu call)
        shared = await asyncio.to_thread(
            get_graph_service().get_cross_document_entities, limit=10
        )
        if not shared:
            return SuggestionResponse(suggestions=_ONBOARDING_SUGGESTIONS[:4])
        return SuggestionResponse(suggestions=_cross_document_suggestions(shared))

    # Fetch document metadata
    session_factory = get_session_factory()
    async with session_factory() as session:
        doc = (
            await session.execute(
                select(DocumentModel).where(DocumentModel.id == document_id)
            )
        ).scalar_one_or_none()

        if doc is None:
            return SuggestionResponse(suggestions=_ONBOARDING_SUGGESTIONS[:4])

        content_type = doc.content_type or "unknown"

        # Fetch section headings (top 5 by order)
        sections_result = await session.execute(
            select(SectionModel.heading)
            .where(SectionModel.document_id == document_id)
            .order_by(SectionModel.section_order)
            .limit(5)
        )
        headings = [r[0] for r in sections_result.all() if r[0]]

    # Fetch entities from Kuzu (I-2: wrap sync Kuzu call)
    entities = await asyncio.to_thread(
        get_graph_service().get_entities_by_type_for_document, document_id
    )

    logger.info(
        "suggestions: doc=%s content_type=%s entities=%d headings=%d",
        document_id,
        content_type,
        sum(len(v) for v in entities.values()),
        len(headings),
    )

    if content_type == "book":
        suggestions = _book_suggestions(entities, headings)
    elif content_type in ("tech_book", "tech_article", "code"):
        suggestions = _technical_suggestions(entities, headings)
    elif content_type in ("video", "audio"):
        suggestions = _video_suggestions(entities, headings)
    else:
        suggestions = _generic_suggestions(entities, headings)

    # Pad with generic fallbacks if templates produced fewer than 4
    fallbacks = [
        "What are the key takeaways from this document?",
        "Summarize the main ideas",
        "What questions should I be asking about this content?",
        "Help me understand the structure of this document",
    ]
    seen = set(suggestions)
    for fb in fallbacks:
        if len(suggestions) >= 4:
            break
        if fb not in seen:
            suggestions.append(fb)

    return SuggestionResponse(suggestions=suggestions[:4])


@router.get("/explorations", response_model=list[ExplorationSuggestion])
async def get_explorations(
    document_id: str = Query(..., description="Document ID to derive entity-pair suggestions for"),
) -> list[ExplorationSuggestion]:
    """Return up to 5 proactive exploration suggestions from Kuzu RELATED_TO entity pairs."""
    pairs = get_graph_service().get_related_entity_pairs_for_document(document_id, limit=5)
    suggestions: list[ExplorationSuggestion] = []
    for name_a, name_b, label, _conf in pairs:
        display_a = name_a.title()
        display_b = name_b.title()
        if label:
            text = f"What is the {label} between {display_a} and {display_b}?"
        else:
            text = f"How is {display_a} related to {display_b}?"
        suggestions.append(ExplorationSuggestion(text=text, entity_names=[name_a, name_b]))
    logger.debug(
        "explorations: doc=%s returned %d suggestions", document_id, len(suggestions)
    )
    return suggestions
