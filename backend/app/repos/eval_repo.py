"""Golden datasets, their questions, and the eval runs scored against them."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentModel, EvalRunModel, GoldenDatasetModel, GoldenQuestionModel


class EvalRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def question_document_ids(self, dataset_id: str) -> set[str]:
        """The documents a dataset's included questions name: what /search is scoped to."""
        result = await self.session.execute(
            select(GoldenQuestionModel.source_document_id)
            .where(
                GoldenQuestionModel.dataset_id == dataset_id,
                GoldenQuestionModel.included.is_(True),
            )
            .distinct()
        )
        return {d for d in result.scalars() if d}

    async def missing_document_ids(self, doc_ids: set[str]) -> set[str]:
        if not doc_ids:
            return set()
        result = await self.session.execute(
            select(DocumentModel.id).where(DocumentModel.id.in_(doc_ids))
        )
        return doc_ids - set(result.scalars())

    async def dataset_missing_document_ids(self, dataset_id: str) -> set[str]:
        # One LEFT JOIN: this runs per dataset on a list the UI polls during generation.
        result = await self.session.execute(
            select(GoldenQuestionModel.source_document_id)
            .outerjoin(DocumentModel, DocumentModel.id == GoldenQuestionModel.source_document_id)
            .where(
                GoldenQuestionModel.dataset_id == dataset_id,
                GoldenQuestionModel.included.is_(True),
                DocumentModel.id.is_(None),
            )
            .distinct()
        )
        return {d for d in result.scalars() if d}

    async def runs(
        self,
        *,
        dataset_name: str | None,
        eval_kind: str | None,
        model: str | None,
        offset: int,
        limit: int,
    ) -> Sequence[EvalRunModel]:
        query = select(EvalRunModel).order_by(EvalRunModel.run_at.desc())
        if dataset_name is not None:
            query = query.where(EvalRunModel.dataset_name == dataset_name)
        if eval_kind is not None:
            query = query.where(EvalRunModel.eval_kind == eval_kind)
        if model is not None:
            query = query.where(EvalRunModel.model_used == model)
        result = await self.session.execute(query.offset(offset).limit(limit))
        return result.scalars().all()

    async def count_included_questions(self, dataset_id: str) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(GoldenQuestionModel)
            .where(
                GoldenQuestionModel.dataset_id == dataset_id,
                GoldenQuestionModel.included.is_(True),
            )
        )
        return int(result.scalar_one())

    async def latest_run(self, dataset_name: str) -> EvalRunModel | None:
        """Latest successful run: failed rows show in the Runs tab but must not blank out a
        dataset's last-known metrics."""
        result = await self.session.execute(
            select(EvalRunModel)
            .where(EvalRunModel.dataset_name == dataset_name, EvalRunModel.status != "failed")
            .order_by(EvalRunModel.run_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def delete_questions(self, dataset_id: str) -> None:
        """Uncommitted."""
        await self.session.execute(
            delete(GoldenQuestionModel).where(GoldenQuestionModel.dataset_id == dataset_id)
        )

    async def runs_for_dataset(self, dataset_id: str) -> Sequence[EvalRunModel]:
        result = await self.session.execute(
            select(EvalRunModel)
            .where(EvalRunModel.dataset_name == dataset_id)
            .order_by(EvalRunModel.run_at.desc())
        )
        return result.scalars().all()

    async def dataset_names(self, dataset_ids: Collection[str]) -> dict[str, str]:
        result = await self.session.execute(
            select(GoldenDatasetModel.id, GoldenDatasetModel.name).where(
                GoldenDatasetModel.id.in_(dataset_ids)
            )
        )
        return dict(result.tuples().all())

    async def datasets(self, status: str | None) -> list[GoldenDatasetModel]:
        query = select(GoldenDatasetModel).order_by(GoldenDatasetModel.created_at.desc())
        if status:
            query = query.where(GoldenDatasetModel.status == status)
        return list((await self.session.execute(query)).scalars().all())

    async def questions(
        self, dataset_id: str, *, offset: int = 0, limit: int | None = None, included_only=False
    ) -> Sequence[GoldenQuestionModel]:
        query = select(GoldenQuestionModel).where(GoldenQuestionModel.dataset_id == dataset_id)
        if included_only:
            query = query.where(GoldenQuestionModel.included.is_(True))
        query = query.order_by(GoldenQuestionModel.created_at).offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return (await self.session.execute(query)).scalars().all()

    async def relink_questions(self, dataset_id: str, old_ids: Collection[str], new_id: str) -> int:
        """Point questions sourced from `old_ids` at `new_id`, chunk unknown; rows changed."""
        result = await self.session.execute(
            update(GoldenQuestionModel)
            .where(
                GoldenQuestionModel.dataset_id == dataset_id,
                GoldenQuestionModel.source_document_id.in_(old_ids),
            )
            .values(source_document_id=new_id, source_chunk_id="")
        )
        return result.rowcount
