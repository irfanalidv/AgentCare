"""
Experiment 2: Longitudinal trend detection.

Generates simulated trajectories (improving / stable / deteriorating) with
controlled noise, runs detect_trend, reports confusion matrix and per-window
accuracy. Saves CSV + plots.

Usage:
    python -m experiments.exp02_trend_detection \
        --output experiments/output/02_trend_detection
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import confusion_matrix

from agentcare.analysis.trend import detect_trend


def _gen(arch: str, n: int, rng: random.Random) -> list[float]:
    if arch == "stable":
        base = rng.uniform(2.0, 4.0)
        return [round(max(0.0, min(10.0, base + rng.gauss(0, 0.5))), 2) for _ in range(n)]
    if arch == "improving":
        start = rng.uniform(6.0, 8.0)
        end = rng.uniform(1.5, 3.0)
        return [
            round(max(0.0, min(10.0, start + (end - start) * (i / max(1, n - 1)) + rng.gauss(0, 0.4))), 2)
            for i in range(n)
        ]
    if arch == "deteriorating":
        start = rng.uniform(1.5, 3.0)
        end = rng.uniform(6.5, 8.5)
        return [
            round(max(0.0, min(10.0, start + (end - start) * (i / max(1, n - 1)) + rng.gauss(0, 0.4))), 2)
            for i in range(n)
        ]
    raise ValueError(arch)


def run(output_dir: str, n_per_arch: int = 200, window_sizes: list[int] | None = None) -> dict:
    window_sizes = window_sizes or [3, 5, 8]
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    archetypes = ["stable", "improving", "deteriorating"]
    rng = random.Random(7)

    results_per_window = {}
    for w in window_sizes:
        y_true = []
        y_pred = []
        for arch in archetypes:
            for _ in range(n_per_arch):
                series = _gen(arch, w, rng)
                tr = detect_trend(series)
                y_true.append(arch)
                y_pred.append(tr.direction)

        cm = confusion_matrix(y_true, y_pred, labels=archetypes)
        acc = float(np.mean([t == p for t, p in zip(y_true, y_pred)]))
        results_per_window[str(w)] = {
            "accuracy": acc,
            "confusion": cm.tolist(),
            "labels": archetypes,
        }

        # Plot confusion
        fig, ax = plt.subplots(figsize=(4, 3.5))
        ax.imshow(cm, cmap="Blues")
        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]):
                ax.text(j, i, str(cm[i, j]), ha="center", va="center")
        ax.set_xticks(range(len(archetypes))); ax.set_xticklabels(archetypes, rotation=20)
        ax.set_yticks(range(len(archetypes))); ax.set_yticklabels(archetypes)
        ax.set_xlabel("Predicted"); ax.set_ylabel("Actual")
        ax.set_title(f"Trend detection (window={w}, acc={acc:.2f})")
        fig.tight_layout()
        fig.savefig(out / f"confusion_w{w}.png", dpi=140)
        plt.close(fig)

    # Accuracy vs window plot
    fig, ax = plt.subplots(figsize=(4, 3))
    ws = sorted(int(k) for k in results_per_window.keys())
    accs = [results_per_window[str(w)]["accuracy"] for w in ws]
    ax.plot(ws, accs, "o-")
    ax.set_xlabel("Window size (sessions)")
    ax.set_ylabel("Accuracy")
    ax.set_title("Trend detection accuracy vs window size")
    ax.set_ylim(0, 1.05)
    fig.tight_layout()
    fig.savefig(out / "accuracy_vs_window.png", dpi=140)
    plt.close(fig)

    summary = {"n_per_archetype": n_per_arch, "by_window": results_per_window}
    with open(out / "metrics.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="experiments/output/02_trend_detection")
    p.add_argument("--n-per-arch", type=int, default=200)
    args = p.parse_args()
    run(args.output, n_per_arch=args.n_per_arch)


if __name__ == "__main__":
    main()
