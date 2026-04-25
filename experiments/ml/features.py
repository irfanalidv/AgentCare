"""
Feature engineering for the predictive layer.

Given a list of session-level burnout records for one employee, produce a flat
feature vector summarising the trajectory. These are the features fed into the
classifier in `train.py`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


FEATURE_NAMES: list[str] = [
    "n_sessions",
    "ee_mean", "ee_std", "ee_slope", "ee_max", "ee_last",
    "dp_mean", "dp_std", "dp_slope", "dp_max", "dp_last",
    "pa_mean", "pa_std", "pa_slope", "pa_max", "pa_last",
    "composite_mean", "composite_std", "composite_slope", "composite_max", "composite_last",
    "high_band_share",
    "high_acuity_any",
    "stressor_workload_share",
    "stressor_interpersonal_share",
    "engagement_low_share",
    "sessions_per_week",
]


@dataclass
class FeatureVector:
    employee_id: str
    values: list[float]
    feature_names: list[str]

    def as_dict(self) -> dict[str, float]:
        return dict(zip(self.feature_names, self.values))


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _slope(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = _mean(xs)
    num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(xs))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den else 0.0


def featurise_sessions(
    sessions: list[dict[str, Any]],
    *,
    employee_id: str,
    sessions_per_week: float = 1.0,
) -> FeatureVector:
    """
    Build a feature vector from oldest-first session entries.

    Each session dict is expected to contain keys produced by
    `process_wellness_execution`: ee_score, dp_score, pa_score, composite_score,
    risk_band, high_acuity_flag, primary_stressor, engagement_level.
    """
    n = len(sessions)
    if n == 0:
        return FeatureVector(employee_id, [0.0] * len(FEATURE_NAMES), FEATURE_NAMES)

    ee = [float(s.get("ee_score", 0.0)) for s in sessions]
    dp = [float(s.get("dp_score", 0.0)) for s in sessions]
    pa = [float(s.get("pa_score", 0.0)) for s in sessions]
    comp = [float(s.get("composite_score", 0.0)) for s in sessions]

    bands = [str(s.get("risk_band", "low")) for s in sessions]
    acuity = [bool(s.get("high_acuity_flag", False)) for s in sessions]
    stressors = [str(s.get("primary_stressor") or "unclear") for s in sessions]
    engagement = [str(s.get("engagement_level") or "medium") for s in sessions]

    high_band_share = sum(1 for b in bands if b == "high") / n
    high_acuity_any = 1.0 if any(acuity) else 0.0
    stressor_workload_share = sum(1 for s in stressors if s == "workload") / n
    stressor_interpersonal_share = sum(1 for s in stressors if s == "interpersonal") / n
    engagement_low_share = sum(1 for e in engagement if e == "low") / n

    values = [
        float(n),
        _mean(ee), _std(ee), _slope(ee), max(ee), ee[-1],
        _mean(dp), _std(dp), _slope(dp), max(dp), dp[-1],
        _mean(pa), _std(pa), _slope(pa), max(pa), pa[-1],
        _mean(comp), _std(comp), _slope(comp), max(comp), comp[-1],
        high_band_share,
        high_acuity_any,
        stressor_workload_share,
        stressor_interpersonal_share,
        engagement_low_share,
        float(sessions_per_week),
    ]

    return FeatureVector(
        employee_id=employee_id,
        values=[round(v, 4) for v in values],
        feature_names=FEATURE_NAMES,
    )


def label_from_future_sessions(
    future_sessions: list[dict[str, Any]],
    *,
    ee_threshold: int = 7,
    dp_threshold: int = 6,
) -> int:
    """
    Binary label: 1 if any future session shows EE >= ee_threshold AND
    DP >= dp_threshold (Maslach high-burnout criterion approximation), else 0.
    """
    for s in future_sessions:
        ee = float(s.get("ee_score", 0.0))
        dp = float(s.get("dp_score", 0.0))
        if ee >= ee_threshold and dp >= dp_threshold:
            return 1
    return 0
