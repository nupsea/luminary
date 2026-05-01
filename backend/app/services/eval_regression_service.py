"""Detect evaluation metric regressions against a moving baseline."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EvalRunModel

TRACKED_METRICS = ("hit_rate_5", "mrr", "faithfulness")


@dataclass(frozen=True)
class EvalRegression:
    dataset: str
    metric: str
    current_value: float
    baseline_value: float
    drop_pct: float
    eval_kind: str | None


async def detect_regressions(
    db: AsyncSession,
    *,
    window: int = 5,
    threshold_pct: float = 0.05,
) -> list[EvalRegression]:
    """Return metric drops where latest value is threshold_pct below prior-window mean."""
    result = await db.execute(
        select(EvalRunModel).order_by(
            EvalRunModel.dataset_name,
            EvalRunModel.eval_kind,
            EvalRunModel.run_at.desc(),
        )
    )
    grouped: dict[tuple[str, str | None], list[EvalRunModel]] = {}
    for run in result.scalars().all():
        grouped.setdefault((run.dataset_name, run.eval_kind), []).append(run)

    regressions: list[EvalRegression] = []
    for (dataset, eval_kind), runs in grouped.items():
        if len(runs) < 2:
            continue
        current = runs[0]
        baseline_runs = runs[1 : window + 1]
        for metric in TRACKED_METRICS:
            current_value = getattr(current, metric)
            baseline_values = [
                getattr(run, metric)
                for run in baseline_runs
                if getattr(run, metric) is not None
            ]
            if current_value is None or not baseline_values:
                continue
            baseline = sum(baseline_values) / len(baseline_values)
            if baseline <= 0:
                continue
            drop_pct = (baseline - current_value) / baseline
            if drop_pct >= threshold_pct:
                regressions.append(
                    EvalRegression(
                        dataset=dataset,
                        metric=metric,
                        current_value=float(current_value),
                        baseline_value=float(baseline),
                        drop_pct=float(drop_pct),
                        eval_kind=eval_kind,
                    )
                )
    return sorted(regressions, key=lambda item: item.drop_pct, reverse=True)
