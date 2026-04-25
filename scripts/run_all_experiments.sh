#!/usr/bin/env bash
# Run the full end-sem experimental pipeline end-to-end.
# Reproduces every figure in the report from scratch.
#
# Prereq:
#     pip install -r experiments/requirements.txt
#
# Usage:
#     bash scripts/run_all_experiments.sh
#     bash scripts/run_all_experiments.sh --use-llm   # uses Mistral API
set -euo pipefail

USE_LLM=0
if [[ "${1:-}" == "--use-llm" ]]; then
    USE_LLM=1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Ensure both the package and the experiments tree are importable
export PYTHONPATH="${ROOT}/src:${ROOT}:${PYTHONPATH:-}"

echo "==> Generating synthetic corpus"
python -c "from experiments.ml.synth_corpus import generate_corpus; generate_corpus(n_per_archetype=60, n_sessions=8, horizon_start=4, seed=42, output_path='experiments/data/synthetic_corpus.jsonl')"

echo "==> Experiment 1: extraction quality"
python experiments/exp01_extraction_quality.py \
    --corpus experiments/data/synthetic_corpus.jsonl \
    --output experiments/output/01_extraction_quality \
    --use-llm "$USE_LLM"

echo "==> Experiment 2: trend detection"
python experiments/exp02_trend_detection.py \
    --output experiments/output/02_trend_detection

echo "==> Experiment 3: predictive model"
python experiments/exp03_predictive_model.py \
    --corpus experiments/data/synthetic_corpus.jsonl \
    --output experiments/output/03_predictive_model \
    --use-llm "$USE_LLM"

echo "==> Experiment 4: adversarial robustness"
python experiments/exp04_adversarial.py \
    --output experiments/output/04_adversarial

echo "==> All experiments complete. Outputs in experiments/output/"
