"""
Experiment 4: Robustness on ambiguous / adversarial transcripts.

Tests how the regex+LLM extractor behaves on:
    - Empty / very short transcripts
    - Off-topic chatter
    - Sarcasm
    - Mixed signals (positive + negative in same transcript)
    - Crisis cues embedded in otherwise low-signal text

Reports false-positive rate (extracting high scores when none warranted) and
false-negative rate (missing crisis signals).

Usage:
    python -m experiments.exp04_adversarial \
        --output experiments/output/04_adversarial
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentcare.analysis.burnout import analyze_burnout_context


# Each tuple: (transcript, expected_band, expected_high_acuity)
ADVERSARIAL_CASES: list[tuple[str, str, bool]] = [
    # --- Empty / short ---
    ("", "low", False),
    ("Hello.", "low", False),
    ("Yes.", "low", False),

    # --- Off-topic ---
    ("I made pasta for dinner. The garden is doing well. We watched a movie.", "low", False),
    ("My team won the cricket match yesterday. It was great.", "low", False),

    # --- Sarcasm (treat as ambiguous; should not over-flag) ---
    ("Oh sure, I am totally fine. Everything is wonderful.", "low", False),
    ("Yeah I love working sixty hour weeks, it's my hobby.", "low", False),

    # --- Mixed signals ---
    ("I am tired but the team is great and I shipped two things this week.", "low", False),
    ("Workload is heavy but I am sleeping fine and feel productive.", "low", False),

    # --- Genuine high-burnout (should flag) ---
    (
        "I am completely exhausted. I cannot sleep. I do not care anymore. "
        "I am missing deadlines and I feel useless.",
        "high",
        False,
    ),

    # --- Embedded crisis ---
    (
        "Things are okay at work I guess. Honestly some days I do not want to wake up.",
        "high",
        True,
    ),
    (
        "Fine. Tired. I cannot take this anymore.",
        "high",
        True,
    ),
]


def run(output_dir: str) -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for transcript, expected_band, expected_acuity in ADVERSARIAL_CASES:
        a = analyze_burnout_context(transcript=transcript)
        rows.append({
            "transcript": transcript,
            "expected_band": expected_band,
            "pred_band": a.risk_band,
            "expected_acuity": expected_acuity,
            "pred_acuity": a.high_acuity_flag,
            "composite": a.composite_score,
            "ee_hits": a.ee_hits,
            "dp_hits": a.dp_hits,
            "pa_hits": a.pa_hits,
        })

    n = len(rows)
    band_correct = sum(1 for r in rows if r["pred_band"] == r["expected_band"])
    acuity_correct = sum(1 for r in rows if r["pred_acuity"] == r["expected_acuity"])

    # Errors
    fp_band = [r for r in rows if r["expected_band"] == "low" and r["pred_band"] != "low"]
    fn_band = [r for r in rows if r["expected_band"] == "high" and r["pred_band"] != "high"]
    fn_acuity = [r for r in rows if r["expected_acuity"] is True and r["pred_acuity"] is False]
    fp_acuity = [r for r in rows if r["expected_acuity"] is False and r["pred_acuity"] is True]

    metrics = {
        "n_cases": n,
        "band_accuracy": band_correct / n,
        "acuity_accuracy": acuity_correct / n,
        "band_false_positives": len(fp_band),
        "band_false_negatives": len(fn_band),
        "acuity_false_negatives": len(fn_acuity),
        "acuity_false_positives": len(fp_acuity),
    }

    with open(out / "metrics.json", "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2)
    with open(out / "details.json", "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2)

    print(json.dumps(metrics, indent=2))
    return metrics


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="experiments/output/04_adversarial")
    args = p.parse_args()
    run(args.output)


if __name__ == "__main__":
    main()
