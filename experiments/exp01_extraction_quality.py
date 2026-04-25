"""
Experiment 1: Burnout extraction quality.

Runs the regex layer (and optionally the LLM layer) over the synthetic corpus,
compares predicted dimension scores against latent ground truth, reports
MAE / RMSE / banded accuracy. Saves CSV + plots.

Usage:
    python -m experiments.exp01_extraction_quality \
        --corpus experiments/data/synthetic_corpus.jsonl \
        --output experiments/output/01_extraction_quality \
        --use-llm 0
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from agentcare.analysis.burnout import analyze_burnout_context
from agentcare.extraction.burnout import extract_burnout_fields


def _band(score: float) -> str:
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    return "low"


def run(corpus_path: str, output_dir: str, use_llm: bool) -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    with open(corpus_path, "r", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            transcript = r["transcript"]

            llm_ee = llm_dp = llm_pa = None
            if use_llm:
                ext = extract_burnout_fields(transcript)
                llm_ee = ext.emotional_exhaustion_0_10
                llm_dp = ext.depersonalisation_0_10
                llm_pa = ext.reduced_accomplishment_0_10

            analysis = analyze_burnout_context(
                transcript=transcript,
                llm_ee=llm_ee, llm_dp=llm_dp, llm_pa=llm_pa,
            )

            rows.append({
                "employee_id": r["employee_id"],
                "session_index": r["session_index"],
                "archetype": r["archetype"],
                "true_ee": r["latent_ee"],
                "true_dp": r["latent_dp"],
                "true_pa": r["latent_pa"],
                "pred_ee": analysis.ee_score,
                "pred_dp": analysis.dp_score,
                "pred_pa": analysis.pa_score,
                "pred_composite": analysis.composite_score,
                "true_band": _band(0.45 * r["latent_ee"] + 0.35 * r["latent_dp"] + 0.20 * r["latent_pa"]),
                "pred_band": analysis.risk_band,
                "high_acuity": analysis.high_acuity_flag,
            })

    # Metrics
    def _mae(a: list[float], b: list[float]) -> float:
        return float(np.mean(np.abs(np.array(a) - np.array(b))))

    def _rmse(a: list[float], b: list[float]) -> float:
        return float(math.sqrt(np.mean((np.array(a) - np.array(b)) ** 2)))

    metrics = {
        "n": len(rows),
        "ee_mae": _mae([r["true_ee"] for r in rows], [r["pred_ee"] for r in rows]),
        "ee_rmse": _rmse([r["true_ee"] for r in rows], [r["pred_ee"] for r in rows]),
        "dp_mae": _mae([r["true_dp"] for r in rows], [r["pred_dp"] for r in rows]),
        "dp_rmse": _rmse([r["true_dp"] for r in rows], [r["pred_dp"] for r in rows]),
        "pa_mae": _mae([r["true_pa"] for r in rows], [r["pred_pa"] for r in rows]),
        "pa_rmse": _rmse([r["true_pa"] for r in rows], [r["pred_pa"] for r in rows]),
        "band_accuracy": float(np.mean([r["true_band"] == r["pred_band"] for r in rows])),
        "use_llm": use_llm,
    }

    # Persist CSV
    import csv
    keys = list(rows[0].keys())
    with open(out / "predictions.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # Scatter plots
    for dim, true_key, pred_key in [
        ("EE", "true_ee", "pred_ee"),
        ("DP", "true_dp", "pred_dp"),
        ("PA", "true_pa", "pred_pa"),
    ]:
        fig, ax = plt.subplots(figsize=(4, 4))
        xs = [r[true_key] for r in rows]
        ys = [r[pred_key] for r in rows]
        ax.scatter(xs, ys, alpha=0.3, s=10)
        ax.plot([0, 10], [0, 10], "k--", linewidth=1)
        ax.set_xlim(0, 10); ax.set_ylim(0, 10)
        ax.set_xlabel(f"True {dim}")
        ax.set_ylabel(f"Predicted {dim}")
        ax.set_title(f"{dim} extraction (LLM={'on' if use_llm else 'off'})")
        fig.tight_layout()
        fig.savefig(out / f"scatter_{dim.lower()}.png", dpi=140)
        plt.close(fig)

    with open(out / "metrics.json", "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2)

    print(json.dumps(metrics, indent=2))
    return metrics


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", default="experiments/data/synthetic_corpus.jsonl")
    p.add_argument("--output", default="experiments/output/01_extraction_quality")
    p.add_argument("--use-llm", type=int, default=0)
    args = p.parse_args()
    run(args.corpus, args.output, bool(args.use_llm))


if __name__ == "__main__":
    main()
