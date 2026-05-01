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


def _fallback_questions(chunk_text: str, count: int) -> list[dict[str, str]]:
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", chunk_text)
        if len(s.strip().split()) >= 5
    ]
    if not sentences:
        hint = chunk_text[:240].strip()
        return [
            {
                "question": "What is the main point of this source passage?",
                "answer": hint or "The passage contains the answer.",
                "context_hint": hint,
            }
        ][:count]

    questions: list[dict[str, str]] = []
    for idx, sentence in enumerate(sentences[:count], start=1):
        hint = sentence[:240].strip()
        questions.append(
            {
                "question": f"What does the source explain in point {idx}?",
                "answer": hint,
                "context_hint": hint,
            }
        )
    return questions


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


def _quality_filter(
    questions: list[dict[str, Any]],
    source_chunk: ChunkModel,
) -> list[dict[str, str]]:
    source_text_norm = _normalize_text(source_chunk.text)
    filtered: list[dict[str, str]] = []
    for raw in questions:
        question = str(raw.get("question", "")).strip()
        answer = str(raw.get("answer") or raw.get("ground_truth_answer") or "").strip()
        context_hint = str(raw.get("context_hint", "")).strip()
        if not question or len(answer) < 5 or not context_hint:
            continue
        if _normalize_text(context_hint) not in source_text_norm:
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
    prompt = (
        "Generate grounded golden evaluation questions from the source text. "
        "Return strict JSON only: {\"questions\":[{\"question\":\"...\","
        "\"answer\":\"...\",\"context_hint\":\"exact substring from source\"}]}. "
        "Every answer must be supported by the source. Every context_hint must be an exact "
        f"substring of the source. Generate {count} questions.\n\nSOURCE:\n{chunk_text[:6000]}"
    )
    settings = get_settings()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "timeout": 90,
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
    schedule: bool = True,
) -> GoldenDatasetModel:
    model = generator_model or get_settings().LITELLM_DEFAULT_MODEL
    dataset = GoldenDatasetModel(
        id=str(uuid.uuid4()),
        name=name,
        description=description,
        size=size,
        generator_model=model,
        source_document_ids=document_ids,
        status="pending",
        generated_count=0,
        target_count=target_count_for(size, len(document_ids)),
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
            for document_id in dataset.source_document_ids:
                if dataset.generated_count >= dataset.target_count:
                    break
                result = await session.execute(
                    select(ChunkModel)
                    .where(ChunkModel.document_id == document_id)
                    .order_by(ChunkModel.chunk_index)
                    .limit(chunks_per_doc)
                )
                chunks = list(result.scalars().all())
                for chunk in chunks:
                    if dataset.generated_count >= dataset.target_count:
                        break
                    remaining = dataset.target_count - dataset.generated_count
                    count = min(questions_per_chunk, remaining)
                    try:
                        raw_questions = await _generate_questions_for_chunk(
                            chunk.text, count, dataset.generator_model
                        )
                    except Exception as exc:
                        logger.warning(
                            "golden question LLM generation failed; using fallback: %s", exc
                        )
                        raw_questions = _fallback_questions(chunk.text, count)
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
