"""Generate DB-backed golden evaluation datasets from ingested chunks."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session_factory
from app.models import ChunkModel, EvalRunModel, GoldenDatasetModel, GoldenQuestionModel
from app.services.golden_quality import (
    build_generation_prompt,
    extract_json_object,
    is_structural_chunk,
    quality_filter,
)
from app.services.llm import get_llm_service

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


async def _generate_questions_for_chunk(
    chunk_text: str, count: int, model: str
) -> list[dict[str, str]]:
    settings = get_settings()
    api_base = settings.OLLAMA_URL if model.startswith("ollama/") else None
    content = await get_llm_service().complete(
        messages=[{"role": "user", "content": build_generation_prompt(chunk_text, count)}],
        model=model,
        timeout=300,
        api_base=api_base,
    )
    parsed = extract_json_object(content)
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
                    if is_structural_chunk(chunk.text):
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
                    accepted = quality_filter(raw_questions, chunk.text)[:count]
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
