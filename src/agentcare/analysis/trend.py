"""Longitudinal trend detection over per-person wellness score history."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class TrendResult:
    n: int
    slope_per_session: float
    mk_statistic: float
    mk_z: float
    mk_p_value: float
    direction: str
    consecutive_deteriorating: int
    triage_trigger: bool


def _ols_slope(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = 0.0
    denominator = 0.0
    for i, value in enumerate(values):
        dx = i - x_mean
        numerator += dx * (value - y_mean)
        denominator += dx * dx
    return numerator / denominator if denominator else 0.0


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _mann_kendall(values: list[float]) -> tuple[float, float, float]:
    n = len(values)
    if n < 3:
        return 0.0, 0.0, 1.0

    statistic = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            if values[j] > values[i]:
                statistic += 1
            elif values[j] < values[i]:
                statistic -= 1

    counts: dict[float, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    ties_term = sum(t * (t - 1) * (2 * t + 5) for t in counts.values() if t > 1)
    variance = (n * (n - 1) * (2 * n + 5) - ties_term) / 18.0
    if variance <= 0:
        return float(statistic), 0.0, 1.0

    if statistic > 0:
        z_score = (statistic - 1) / math.sqrt(variance)
    elif statistic < 0:
        z_score = (statistic + 1) / math.sqrt(variance)
    else:
        z_score = 0.0

    p_value = 2.0 * (1.0 - _norm_cdf(abs(z_score)))
    return float(statistic), float(z_score), float(p_value)


def _consecutive_deteriorating(values: list[float]) -> int:
    if len(values) < 2:
        return 0
    run = 0
    for i in range(len(values) - 1, 0, -1):
        if values[i] > values[i - 1]:
            run += 1
        else:
            break
    return run


def detect_trend(
    composite_scores: list[float],
    *,
    deterioration_run_threshold: int = 3,
    score_threshold: float = 7.0,
    p_value_threshold: float = 0.10,
) -> TrendResult:
    n = len(composite_scores)
    if n == 0:
        return TrendResult(0, 0.0, 0.0, 0.0, 1.0, "stable", 0, False)

    slope = _ols_slope(composite_scores)
    statistic, z_score, p_value = _mann_kendall(composite_scores)

    if p_value < p_value_threshold:
        direction = "deteriorating" if statistic > 0 else "improving" if statistic < 0 else "stable"
    elif slope >= 0.5:
        direction = "deteriorating"
    elif slope <= -0.5:
        direction = "improving"
    else:
        direction = "stable"

    consecutive = _consecutive_deteriorating(composite_scores)
    latest = composite_scores[-1]
    triage = (
        consecutive >= deterioration_run_threshold
        or latest >= score_threshold
        or (direction == "deteriorating" and latest >= 5.0)
    )

    return TrendResult(
        n=n,
        slope_per_session=round(slope, 3),
        mk_statistic=round(statistic, 3),
        mk_z=round(z_score, 3),
        mk_p_value=round(p_value, 4),
        direction=direction,
        consecutive_deteriorating=consecutive,
        triage_trigger=triage,
    )
