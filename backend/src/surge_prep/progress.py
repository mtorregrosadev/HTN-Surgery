"""Progress across attempts, computed from stored scorecards (works with any Store)."""
from __future__ import annotations

from .coaching import COMPONENTS, component_scores
from .models import ProgressSummary, ResultRecord, TrendPoint


def summarize_progress(records: list[ResultRecord]) -> ProgressSummary:
    """`records` are expected oldest first. Returns an empty summary for no attempts."""
    if not records:
        return ProgressSummary(attempts=0)
    scores = [r.metrics.illustrative_score_percent for r in records]
    per_component: dict[str, list[float]] = {name: [] for name, *_ in COMPONENTS}
    for record in records:
        for name, value in component_scores(record.metrics).items():
            per_component[name].append(value)
    averages = {name: round(sum(v) / len(v), 1) for name, v in per_component.items()}
    weights = {name: weight for name, _, weight, _ in COMPONENTS}
    weakest = max(averages, key=lambda name: weights[name] * (100.0 - averages[name]))
    return ProgressSummary(
        attempts=len(records),
        latest_score_percent=round(scores[-1], 1),
        best_score_percent=round(max(scores), 1),
        average_score_percent=round(sum(scores) / len(scores), 1),
        improvement_points=round(scores[-1] - scores[0], 1) if len(scores) > 1 else None,
        weakest_component=weakest,
        component_averages=averages,
        trend=[TrendPoint(session_id=r.session_id, completed_at=r.completed_at,
                          score_percent=round(r.metrics.illustrative_score_percent, 1)) for r in records],
    )
