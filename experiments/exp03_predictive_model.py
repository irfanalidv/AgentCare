"""
Experiment 3: Predictive modelling of burnout at horizon.

Uses the synthetic corpus. For each employee:
    - Take sessions [0, horizon_start) as the observation window.
    - Run regex+LLM extraction (LLM optional) on each session to produce
      session-level burnout records.
    - Featurise the window with ml.features.featurise_sessions.
    - Use the corpus-level label (label_burnout_at_horizon) as ground truth.

Trains LR / RF / HGBT, plus an ablation that drops the burnout-derived features
to see how much the LLM/regex layer contributes vs raw composite scores alone.

Usage:
    python -m experiments.exp03_predictive_model \
        --corpus experiments/data/synthetic_corpus.jsonl \
        --output experiments/output/03_predictive_model \
        --use-llm 0
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from agentcare.analysis.burnout import analyze_burnout_context
from agentcare.extraction.burnout import extract_burnout_fields
from experiments.ml.features import FEATURE_NAMES, featurise_sessions
from experiments.ml.train import TrainConfig, train_all


def _build_session_record(transcript: str, use_llm: bool) -> dict:
    llm_ee = llm_dp = llm_pa = None
    primary_stressor = None
    engagement_level = None
    if use_llm:
        ext = extract_burnout_fields(transcript)
        llm_ee = ext.emotional_exhaustion_0_10
        llm_dp = ext.depersonalisation_0_10
        llm_pa = ext.reduced_accomplishment_0_10
        primary_stressor = ext.primary_stressor
        engagement_level = ext.engagement_level

    analysis = analyze_burnout_context(
        transcript=transcript, llm_ee=llm_ee, llm_dp=llm_dp, llm_pa=llm_pa,
    )
    return {
        "ee_score": analysis.ee_score,
        "dp_score": analysis.dp_score,
        "pa_score": analysis.pa_score,
        "composite_score": analysis.composite_score,
        "risk_band": analysis.risk_band,
        "high_acuity_flag": analysis.high_acuity_flag,
        "primary_stressor": primary_stressor,
        "engagement_level": engagement_level,
    }


def run(corpus_path: str, output_dir: str, use_llm: bool) -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    sessions_by_emp: dict[str, list[dict]] = defaultdict(list)
    label_by_emp: dict[str, int] = {}
    horizon_start = None

    with open(corpus_path, "r", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            horizon_start = r["horizon_start"]
            if r["session_index"] < r["horizon_start"]:
                rec = _build_session_record(r["transcript"], use_llm)
                rec["_session_index"] = r["session_index"]
                sessions_by_emp[r["employee_id"]].append(rec)
            label_by_emp[r["employee_id"]] = r["label_burnout_at_horizon"]

    # Sort each employee's sessions by index
    X_rows: list[list[float]] = []
    y_rows: list[int] = []
    eids: list[str] = []
    for eid, sessions in sessions_by_emp.items():
        sessions.sort(key=lambda s: s["_session_index"])
        fv = featurise_sessions(sessions, employee_id=eid)
        X_rows.append(fv.values)
        y_rows.append(label_by_emp[eid])
        eids.append(eid)

    X = np.array(X_rows, dtype=float)
    y = np.array(y_rows, dtype=int)

    print(f"Built feature matrix: X={X.shape}, y={y.shape}, "
          f"positive rate={y.mean():.3f}")

    metrics = train_all(X, y, eids, cfg=TrainConfig(output_dir=str(out)))

    # Ablation: drop LLM-derived features (stressor & engagement shares)
    drop_idxs = [
        FEATURE_NAMES.index("stressor_workload_share"),
        FEATURE_NAMES.index("stressor_interpersonal_share"),
        FEATURE_NAMES.index("engagement_low_share"),
    ]
    keep_idxs = [i for i in range(len(FEATURE_NAMES)) if i not in drop_idxs]
    X_ablated = X[:, keep_idxs]

    ablation_dir = out / "ablation_no_llm_categorical"
    ablation_dir.mkdir(parents=True, exist_ok=True)
    metrics_ablated = train_all(
        X_ablated, y, eids,
        cfg=TrainConfig(output_dir=str(ablation_dir)),
    )

    summary = {
        "horizon_start": horizon_start,
        "n_employees": int(len(y)),
        "positive_rate": float(y.mean()),
        "use_llm": use_llm,
        "full": metrics,
        "ablation_no_llm_categorical": metrics_ablated,
    }
    with open(out / "summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", default="experiments/data/synthetic_corpus.jsonl")
    p.add_argument("--output", default="experiments/output/03_predictive_model")
    p.add_argument("--use-llm", type=int, default=0)
    args = p.parse_args()
    run(args.corpus, args.output, bool(args.use_llm))


if __name__ == "__main__":
    main()
