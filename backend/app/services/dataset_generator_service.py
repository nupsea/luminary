"""Generate DB-backed golden evaluation datasets from ingested chunks."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import litellm
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session_factory
from app.models import ChunkModel, EvalRunModel, GoldenDatasetModel, GoldenQuestionModel

logger = logging.getLogger(__name__)

SIZE_CONFIG: dict[str, tuple[int, int]] = {
    "small": (5, 2),
    "medium": (10, 5),
    "large": (20, 10),
}
MAX_QUESTIONS_PER_DATASET = 1000
DEFAULT_GENERATOR_MODEL = "openai/gpt-4.1"

_background_tasks: set[asyncio.Task] = set()


def target_count_for(size: str, document_count: int) -> int:
    if size not in SIZE_CONFIG:
        raise ValueError(f"invalid dataset size: {size}")
    questions_per_chunk, chunks_per_doc = SIZE_CONFIG[size]
    return min(MAX_QUESTIONS_PER_DATASET, questions_per_chunk * chunks_per_doc * document_count)


def _fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM response did not contain a JSON object")
    return json.loads(stripped[start : end + 1])


_FRONT_BACK_MATTER = frozenset(
    "foreword preface acknowledgments acknowledgement dedication copyright isbn"
    " publisher colophon bibliography index glossary".split()
)


def _is_structural_chunk(text: str) -> bool:
    """Return True for chunks unlikely to yield good content-focused eval questions.

    Skips page headers, TOC entries, front/back matter, and chunks with low
    alphabetic density (tables, code listings, figure captions).
    """
    stripped = text.strip()
    if len(stripped) < 200:
        return True
    words = stripped.split()
    if len(words) < 40:
        return True
    alpha_ratio = sum(1 for c in stripped if c.isalpha()) / len(stripped)
    if alpha_ratio < 0.55:
        return True
    # Skip front/back matter sections (foreword, preface, acknowledgments, etc.)
    lower_words = set(w.strip(".,;:\"'").lower() for w in words[:30])
    if lower_words & _FRONT_BACK_MATTER:
        return True
    # Section-header prefix scan: chunks are emitted as
    # "[doc_title > Section Name — subsection] body...". Reject if the section
    # path itself names front-matter (Part III. Apache Iceberg in Practice
    # preface, "Praise for...", endorsements, etc.).
    header_match = re.match(r"\s*\[([^\]]+)\]", stripped)
    if header_match:
        header = header_match.group(1).lower()
        if any(
            tag in header
            for tag in (
                "foreword", "preface", "acknowledgment", "acknowledgement",
                "dedication", "praise for", "about the author", "introduction",
                "part i.", "part ii.", "part iii.", "part iv.",
            )
        ):
            return True
    return False


def _dedupe_by_embedding(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    questions = [c["question"] for c in candidates]
    if len(questions) < 2:
        return candidates
    try:
        import numpy as np  # noqa: PLC0415

        from app.services.embedder import get_embedding_service  # noqa: PLC0415

        vectors = np.array(get_embedding_service().encode(questions), dtype=np.float32)
        norms = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-10)
        kept: list[int] = []
        for idx, vector in enumerate(norms):
            if not kept:
                kept.append(idx)
                continue
            sims = norms[kept] @ vector
            if not bool(np.any(sims > 0.95)):
                kept.append(idx)
        return [candidates[i] for i in kept]
    except Exception:
        logger.debug("embedding dedupe unavailable; falling back to exact-question dedupe")
        seen: set[str] = set()
        unique: list[dict[str, str]] = []
        for candidate in candidates:
            key = _normalize_text(candidate["question"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return unique


_STOPWORDS = frozenset(
    "a an the is are was were be been being have has had do does did will would could should "
    "may might shall can of in on at to for with by from as into through during about above "
    "between but and or nor not if then that this these those it its we our they their i my "
    "what which who when where how".split()
)


def _hint_grounded(hint_norm: str, source_norm: str) -> bool:
    """True when ≥75% of the non-stopword words in the hint appear in the source."""
    hint_words = [w for w in hint_norm.split() if w not in _STOPWORDS and len(w) > 2]
    if not hint_words:
        return False
    source_words = set(source_norm.split())
    overlap = sum(1 for w in hint_words if w in source_words)
    return overlap / len(hint_words) >= 0.75


def _quality_filter(
    questions: list[dict[str, Any]],
    source_chunk: ChunkModel,
) -> list[dict[str, str]]:
    source_norm = _normalize_text(source_chunk.text)
    filtered: list[dict[str, str]] = []
    for raw in questions:
        question = str(raw.get("question", "")).strip()
        answer = str(raw.get("answer") or raw.get("ground_truth_answer") or "").strip()
        context_hint = str(raw.get("context_hint", "")).strip()
        if not question or len(answer) < 10 or not context_hint:
            continue
        # Reject questions that reference the document instead of the subject matter.
        # Good: "What does Apache Iceberg use to track file-level statistics?"
        # Bad:  "According to the text, what does Iceberg use...?"
        q_lower = question.lower()
        if any(
            phrase in q_lower
            for phrase in (
                # explicit document references
                "according to the text", "according to the guide",
                "according to the source", "according to the passage",
                "according to the author", "according to the document",
                "the text states", "the text says", "the text describes",
                "the text explains", "the text mentions", "the text notes",
                "the text suggests", "the guide states", "the guide describes",
                "the guide mentions", "the source states", "the passage states",
                "the author states", "the author describes", "the author explains",
                "the author mentions", "the author suggests",
                "as stated in", "as described in", "as mentioned in",
                "as noted in", "as explained in",
                # implicit document references
                "according to this", "this text", "this guide", "this source",
                "this passage", "this document", "this section", "this chapter",
                "the text", "the guide", "the source", "the passage",
                "the document", "the section", "the chapter", "the excerpt",
                # passive "is mentioned / listed / highlighted / described"
                "is mentioned", "is listed", "is highlighted", "is described",
                "is stated", "is noted", "is referenced", "is discussed",
                "are mentioned", "are listed", "are highlighted", "are described",
                "are stated", "are noted",
                # generic templates from fallback / bad LLM output
                "what does the source", "what is the main point", "in point ",
                # book metadata / authorship / publication
                "who wrote", "who is the author", "who authored", "who edited",
                "foreword", "preface", "acknowledgment", "dedication",
                "who dedicated", "copyright", "isbn", "publisher", "published by",
                "edition of", "this book", "the book",
                # document structure references
                "page number", "chapter number", "section number",
                "table of contents", "appendix",
            )
        ):
            continue
        # Require the hint to be grounded in the source chunk
        if not _hint_grounded(_normalize_text(context_hint), source_norm):
            continue
        filtered.append(
            {
                "question": question,
                "ground_truth_answer": answer,
                "context_hint": context_hint,
            }
        )
    return _dedupe_by_embedding(filtered)


async def _generate_questions_for_chunk(
    chunk_text: str, count: int, model: str
) -> list[dict[str, str]]:
    rules = (
        f"Generate {count} self-contained knowledge questions from the source text below.\n\n"
        "CRITICAL RULE: Write questions as if testing whether someone has learned this"
        " subject — NOT as reading comprehension about a document.\n\n"
        "GOOD example: 'What file format does Apache Iceberg use to store table metadata?'\n"
        "BAD examples (never do these):\n"
        "  - 'According to the text, what does Iceberg use...?'\n"
        "  - 'What does the guide say about...?'\n"
        "  - 'What is mentioned in this passage about...?'\n"
        "  - 'What is highlighted/listed/described in the source?'\n\n"
        "Rules:\n"
        "- The question must make complete sense to someone who has never seen this"
        " document. No references to 'the text', 'the guide', 'the source',"
        " 'this section', 'the passage', 'the author', or any document.\n"
        "- Ask about concrete facts, definitions, mechanisms, trade-offs, or examples.\n"
        "- The answer must be specific and complete — not 'see the text'.\n"
        "- context_hint must be a verbatim phrase (5-20 words) from the source text.\n"
        "- Do NOT ask about authorship, foreword, preface, dedication, copyright,"
        " ISBN, publisher, or any publication metadata.\n\n"
        "Return ONLY valid JSON:\n"
        '{"questions":[{"question":"...","answer":"...","context_hint":"verbatim"}]}\n\n'
        f"SOURCE:\n{chunk_text[:6000]}"
    )
    settings = get_settings()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": rules}],
        "timeout": 120,
    }
    if model.startswith("ollama/"):
        kwargs["api_base"] = settings.OLLAMA_URL
    response = await litellm.acompletion(**kwargs)
    content = response.choices[0].message.content or ""
    parsed = _extract_json_object(content)
    items = parsed.get("questions", [])
    if not isinstance(items, list):
        raise ValueError("LLM JSON did not include a questions array")
    return [q for q in items if isinstance(q, dict)]


async def create_dataset(
    session: AsyncSession,
    *,
    name: str,
    document_ids: list[str],
    size: str,
    generator_model: str | None,
    description: str | None = None,
    question_count: int | None = None,
    schedule: bool = True,
) -> GoldenDatasetModel:
    model = generator_model or DEFAULT_GENERATOR_MODEL
    target = (
        question_count if question_count is not None else target_count_for(size, len(document_ids))
    )
    dataset = GoldenDatasetModel(
        id=str(uuid.uuid4()),
        name=name,
        description=description,
        size=size,
        generator_model=model,
        source_document_ids=document_ids,
        status="pending",
        generated_count=0,
        target_count=target,
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    if schedule:
        schedule_dataset_generation(dataset.id)
    return dataset


def schedule_dataset_generation(dataset_id: str) -> None:
    _fire_and_forget(_generate_dataset(dataset_id))


async def _generate_dataset(dataset_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        dataset = await session.get(GoldenDatasetModel, dataset_id)
        if dataset is None:
            return
        dataset.status = "generating"
        dataset.error_message = None
        await session.commit()

    try:
        async with factory() as session:
            dataset = await session.get(GoldenDatasetModel, dataset_id)
            if dataset is None:
                return
            questions_per_chunk, chunks_per_doc = SIZE_CONFIG[dataset.size]

            # When target_count exceeds the SIZE_CONFIG ceiling, lift the chunk
            # limit so we sample as many chunks as needed to hit the target.
            size_ceiling = questions_per_chunk * chunks_per_doc * len(dataset.source_document_ids)
            custom_count = dataset.target_count > size_ceiling

            for document_id in dataset.source_document_ids:
                if dataset.generated_count >= dataset.target_count:
                    break
                # Randomize chunk order so we sample across the whole document
                # (front-matter has heavy bias toward generic "what is X about" Qs).
                # Oversample 4x so structural-chunk skips don't starve the run.
                chunk_query = (
                    select(ChunkModel)
                    .where(ChunkModel.document_id == document_id)
                    .order_by(func.random())
                )
                if not custom_count:
                    chunk_query = chunk_query.limit(chunks_per_doc * 4)
                result = await session.execute(chunk_query)
                chunks = list(result.scalars().all())
                for chunk in chunks:
                    if dataset.generated_count >= dataset.target_count:
                        break
                    if _is_structural_chunk(chunk.text):
                        logger.debug("skipping structural chunk %s", chunk.id)
                        continue
                    remaining = dataset.target_count - dataset.generated_count
                    # Ask for 2× headroom so the quality filter has candidates to work with.
                    ask = min(questions_per_chunk * 2, remaining * 2, 20)
                    count = min(questions_per_chunk, remaining)
                    try:
                        raw_questions = await _generate_questions_for_chunk(
                            chunk.text, ask, dataset.generator_model
                        )
                    except Exception as exc:
                        logger.warning("skipping chunk %s — LLM error: %s", chunk.id, exc)
                        continue
                    accepted = _quality_filter(raw_questions, chunk)[:count]
                    for item in accepted:
                        session.add(
                            GoldenQuestionModel(
                                id=str(uuid.uuid4()),
                                dataset_id=dataset.id,
                                question=item["question"],
                                ground_truth_answer=item["ground_truth_answer"],
                                context_hint=item["context_hint"],
                                source_chunk_id=chunk.id,
                                source_document_id=chunk.document_id,
                                quality_score=1.0,
                                included=True,
                            )
                        )
                        dataset.generated_count += 1
                    await session.commit()

            dataset.status = "complete"
            dataset.completed_at = datetime.now(UTC)
            await session.commit()
    except Exception as exc:
        async with factory() as session:
            dataset = await session.get(GoldenDatasetModel, dataset_id)
            if dataset is not None:
                dataset.status = "failed"
                dataset.error_message = str(exc)
                dataset.completed_at = datetime.now(UTC)
                await session.commit()
        logger.exception("golden dataset generation failed for %s", dataset_id)


async def delete_dataset(session: AsyncSession, dataset_id: str) -> bool:
    dataset = await session.get(GoldenDatasetModel, dataset_id)
    if dataset is None:
        return False
    await session.execute(
        delete(GoldenQuestionModel).where(GoldenQuestionModel.dataset_id == dataset_id)
    )
    await session.delete(dataset)
    await session.commit()
    return True


async def count_questions(session: AsyncSession, dataset_id: str) -> int:
    result = await session.execute(
        select(func.count()).select_from(GoldenQuestionModel).where(
            GoldenQuestionModel.dataset_id == dataset_id,
            GoldenQuestionModel.included.is_(True),
        )
    )
    return int(result.scalar_one())


async def latest_run_for_dataset(session: AsyncSession, dataset_name: str) -> EvalRunModel | None:
    result = await session.execute(
        select(EvalRunModel)
        .where(EvalRunModel.dataset_name == dataset_name)
        .order_by(EvalRunModel.run_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
