# AgentCare Experiments

Reproducible benchmark layer for the AgentCare workplace-wellness workflow.
This directory is intentionally **separate from the core `agentcare` package**:
it pulls in heavier ML dependencies (scikit-learn, numpy, matplotlib) that
the runtime workflow does not need.

This layer reproduces every quantitative result reported in the DS-AI
end-semester project report (Section 8).

## Quickstart

From the repository root:

```bash
pip install -r experiments/requirements.txt
bash scripts/run_all_experiments.sh
```

Total runtime on a modern laptop: ~30 seconds (regex-only mode).
Add `--use-llm` to route Experiments 1 and 3 through the Mistral extractor
(requires `MISTRAL_API_KEY` in `.env`; ~1500 API calls).

Outputs land in `experiments/output/<experiment_name>/`.

## Layout

```
experiments/
├── ml/                       Reusable feature engineering + training pipeline
│   ├── features.py           27-dim per-employee feature vector
│   ├── train.py              LR / RF / HGBT pipeline + plots
│   └── synth_corpus.py       Deterministic synthetic corpus generator
├── exp01_extraction_quality.py
├── exp02_trend_detection.py
├── exp03_predictive_model.py
├── exp04_adversarial.py
├── data/                     Generated synthetic corpus lives here
├── output/                   Per-experiment metrics, CSVs, figures, models
├── requirements.txt
└── README.md (this file)
```

## What each experiment measures

**exp01 — Extraction quality.** Compares the regex-layer (and optionally the
LLM-layer) per-dimension scores against the latent ground truth in the
synthetic corpus. Reports MAE/RMSE per dimension and banded accuracy.

**exp02 — Trend detection.** Simulates 200 trajectories per archetype
(stable/improving/deteriorating) at three window sizes (3/5/8 sessions) and
reports the Mann-Kendall + slope detector's classification accuracy.

**exp03 — Predictive modelling.** Trains LR / RF / HGBT classifiers on the
per-employee feature matrix to predict at-horizon burnout (label horizon =
session 4). Group-aware 70/15/15 split by employee. Includes a feature
ablation that drops the LLM-derived categorical features.

**exp04 — Adversarial robustness.** Tests the regex layer against twelve
hand-crafted edge cases (empty, off-topic, sarcastic, mixed-signal, embedded
crisis cues). Reports false-positive and false-negative rates.

## Reproducibility guarantees

- All randomness is seeded (`seed=42` throughout).
- The synthetic corpus is deterministic given the seed: 180 employees ×
  8 sessions = 1,440 transcripts, ~51.7% positive label rate.
- Headline numbers from the regex-only run on the default corpus:
  - Trend detection accuracy at window=8: **0.972**
  - Predictive model F1 (LogReg, test): **0.952**
  - Predictive model ROC-AUC (LogReg, test): **0.997**
  - Adversarial band accuracy: **0.833**, zero false positives.

These are validation numbers for the pipeline mechanics on synthetic data,
not external claims about real-world burnout detection. See report Section
9.2 for the full limitations discussion.
