"""Explain service -- context-grounded explanations and glossary extraction."""

import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from sqlalchemy import delete, select, text

from app.database import get_session_factory
from app.models import GlossaryTermModel, SectionModel
from app.services.llm import get_llm_service
from app.services.retriever import get_retriever

logger = logging.getLogger(__name__)

EXPLAIN_SYSTEM_BASE = (
    "You are explaining a concept using only the context from the source document. "
    "Use only information present in the provided text."
)

MODE_INSTRUCTIONS: dict[str, str] = {
    "plain": "Explain in simple, clear English.",
    "eli5": "Explain as if to a curious 10-year-old, using a concrete everyday analogy.",
    "analogy": "Create a memorable analogy from everyday life that captures the core idea.",
    "formal": "Give the precise formal definition as stated or implied in the source material.",
}

GLOSSARY_SYSTEM = (
    "You are a technical terminology extractor. "
    "You MUST output ONLY a JSON array. No explanations, no preamble, "
    "no markdown. Just the raw JSON array."
)

GLOSSARY_USER_TMPL = (
    "Extract all domain-specific technical terms from this text. "
    "For each term, define it based only on how it is used in the text. "
    "Categorize each term as one of: character, place, concept, "
    "technical, event, or general.\n\n"
    "Text:\n{text}\n\n"
    "Respond with ONLY a JSON array. Example format:\n"
    '[{{"term": "example", "definition": "a sample", "category": "concept"}}]'
)

# Approximate token limit for glossary context (4000 tokens ~ 16000 chars)
_GLOSSARY_CHAR_LIMIT = 16_000


class ExplainService:
    async def stream_explain(
        self,
        text: str,
        document_id: str,
        mode: str,
    ) -> AsyncGenerator[str]:
        """Stream explanation tokens as SSE data events."""
        llm = get_llm_service()

        mode_instruction = MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["plain"])
        system = f"{EXPLAIN_SYSTEM_BASE}\n\n{mode_instruction}"
        prompt = f"Selected text:\n\n{text}\n\nExplain the selected text."

        token_gen = await llm.generate(prompt, system=system, stream=True)
        async for token in token_gen:
            yield f'data: {json.dumps({"token": token})}\n\n'

        yield f'data: {json.dumps({"done": True})}\n\n'

    async def extract_glossary(self, document_id: str) -> list[dict]:
        """Extract technical terms from a document, persist to DB, and return."""
        retriever = get_retriever()
        llm = get_llm_service()

        # Retrieve a broad sample of chunks (high k, filter by document)
        chunks = await retriever.retrieve(
            "definition concept term", document_ids=[document_id], k=50
        )

        # Build text sample, truncate to char limit
        parts: list[str] = []
        total = 0
        for chunk in chunks:
            if total + len(chunk.text) > _GLOSSARY_CHAR_LIMIT:
                remaining = _GLOSSARY_CHAR_LIMIT - total
                if remaining > 200:  # noqa: PLR2004
                    parts.append(chunk.text[:remaining])
                break
            parts.append(chunk.text)
            total += len(chunk.text)

        combined_text = "\n\n".join(parts) if parts else ""
        if not combined_text:
            return []

        prompt = GLOSSARY_USER_TMPL.format(text=combined_text)
        raw = await llm.generate(prompt, system=GLOSSARY_SYSTEM, stream=False)

        # Strip markdown fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0].strip()

        terms = self._parse_glossary_json(raw, document_id)
        if terms is None:
            raise GlossaryParseError(
                "Glossary generation failed -- try again"
            )

        # Persist terms via upsert
        persisted = await self._upsert_terms(document_id, terms)
        return persisted

    def _parse_glossary_json(
        self, raw: str, document_id: str
    ) -> list[dict] | None:
        """Parse LLM glossary output, tolerating common formatting issues."""
        try:
            terms = json.loads(raw)
            if isinstance(terms, list):
                return terms
        except (json.JSONDecodeError, ValueError):
            pass

        # Try to extract a JSON array from the raw text
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            try:
                terms = json.loads(match.group())
                if isinstance(terms, list):
                    return terms
            except (json.JSONDecodeError, ValueError):
                pass

        logger.warning(
            "Glossary parse failed for doc %s: %r",
            document_id, raw[:200],
        )
        return None

    async def _upsert_terms(
        self, document_id: str, terms: list[dict]
    ) -> list[dict]:
        """Upsert glossary terms into DB and return the full persisted list."""
        now = datetime.now(UTC)

        # Load sections for first_mention matching
        async with get_session_factory()() as session:
            sections = (
                await session.execute(
                    select(SectionModel).where(SectionModel.document_id == document_id)
                    .order_by(SectionModel.section_order)
                )
            ).scalars().all()

            for t in terms:
                term_text = t.get("term", "").strip()
                if not term_text:
                    continue
                definition = t.get("definition", "").strip()
                category = t.get("category", "general").strip().lower()

                # Match first mention section
                first_section_id = None
                term_lower = term_text.lower()
                for sec in sections:
                    preview = (sec.preview or "").lower()
                    if term_lower in preview or term_lower in sec.heading.lower():
                        first_section_id = sec.id
                        break

                # Upsert via raw SQL for ON CONFLICT
                await session.execute(
                    text(
                        "INSERT INTO glossary_terms "
                        "(id, document_id, term, definition, first_mention_section_id, "
                        "category, created_at, updated_at) "
                        "VALUES (:id, :doc_id, :term, :definition, :section_id, "
                        ":category, :created_at, :updated_at) "
                        "ON CONFLICT(document_id, term) DO UPDATE SET "
                        "definition = :definition, category = :category, "
                        "first_mention_section_id = :section_id, updated_at = :updated_at"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "doc_id": document_id,
                        "term": term_text,
                        "definition": definition,
                        "section_id": first_section_id,
                        "category": category,
                        "created_at": now.isoformat(),
                        "updated_at": now.isoformat(),
                    },
                )

            await session.commit()

        # Return the full persisted list
        return await self.get_cached_glossary(document_id)

    async def get_cached_glossary(self, document_id: str) -> list[dict]:
        """Return persisted glossary terms without LLM call."""
        async with get_session_factory()() as session:
            rows = (
                await session.execute(
                    select(GlossaryTermModel)
                    .where(GlossaryTermModel.document_id == document_id)
                    .order_by(GlossaryTermModel.term)
                )
            ).scalars().all()

        return [
            {
                "id": r.id,
                "term": r.term,
                "definition": r.definition,
                "first_mention_section_id": r.first_mention_section_id,
                "category": r.category,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]

    async def delete_term(self, term_id: str) -> bool:
        """Delete a single glossary term by ID. Returns True if deleted."""
        async with get_session_factory()() as session:
            result = await session.execute(
                delete(GlossaryTermModel).where(GlossaryTermModel.id == term_id)
            )
            await session.commit()
            return result.rowcount > 0


class GlossaryParseError(Exception):
    pass


_explain_service: ExplainService | None = None


def get_explain_service() -> ExplainService:
    global _explain_service  # noqa: PLW0603
    if _explain_service is None:
        _explain_service = ExplainService()
    return _explain_service
