"""
Train baseline burnout classifiers on a synthetic corpus.

Three baselines, in order of sophistication:
    1. Logistic Regression (interpretable baseline)
    2. Random Forest
    3. Histogram Gradient Boosted Trees (sklearn)

Outputs to experiments/03_predictive_model/output/:
    - metrics.json (precision, recall, F1, ROC-AUC, PR-AUC per model)
    - confusion_<model>.png
    - calibration_<model>.png
    - feature_importance_<model>.png
    - model_<model>.pkl
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from experiments.ml.features import FEATURE_NAMES


@dataclass
class TrainConfig:
    test_size: float = 0.15
    val_size: float = 0.15
    random_state: int = 42
    output_dir: str = "experiments/03_predictive_model/output"


def _split_by_employee(
    X: np.ndarray,
    y: np.ndarray,
    employee_ids: list[str],
    cfg: TrainConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Group-aware split: same employee never appears in two splits."""
    unique_ids = sorted(set(employee_ids))
    rng = np.random.default_rng(cfg.random_state)
    rng.shuffle(unique_ids)

    n = len(unique_ids)
    n_test = int(round(cfg.test_size * n))
    n_val = int(round(cfg.val_size * n))
    test_ids = set(unique_ids[:n_test])
    val_ids = set(unique_ids[n_test : n_test + n_val])

    train_mask = np.array([eid not in test_ids and eid not in val_ids for eid in employee_ids])
    val_mask = np.array([eid in val_ids for eid in employee_ids])
    test_mask = np.array([eid in test_ids for eid in employee_ids])

    return (
        X[train_mask], y[train_mask],
        X[val_mask], y[val_mask],
        X[test_mask], y[test_mask],
    )


def _eval(y_true: np.ndarray, y_pred: np.ndarray, y_proba: np.ndarray) -> dict[str, float]:
    return {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, y_proba)) if len(set(y_true)) > 1 else float("nan"),
        "pr_auc": float(average_precision_score(y_true, y_proba)) if len(set(y_true)) > 1 else float("nan"),
        "n": int(len(y_true)),
        "positive_rate": float(np.mean(y_true)),
    }


def _save_confusion(cm: np.ndarray, name: str, out_dir: Path) -> None:
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(4, 3.5))
    ax.imshow(cm, cmap="Blues")
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center")
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_xticks([0, 1]); ax.set_xticklabels(["No burnout", "Burnout"])
    ax.set_yticks([0, 1]); ax.set_yticklabels(["No burnout", "Burnout"])
    ax.set_title(f"Confusion — {name}")
    fig.tight_layout()
    fig.savefig(out_dir / f"confusion_{name}.png", dpi=140)
    plt.close(fig)


def _save_calibration(y_true: np.ndarray, y_proba: np.ndarray, name: str, out_dir: Path) -> None:
    import matplotlib.pyplot as plt
    if len(set(y_true)) < 2:
        return
    frac_pos, mean_pred = calibration_curve(y_true, y_proba, n_bins=10, strategy="quantile")
    fig, ax = plt.subplots(figsize=(4, 3.5))
    ax.plot([0, 1], [0, 1], "k--", linewidth=1, label="Perfect")
    ax.plot(mean_pred, frac_pos, "o-", label=name)
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Fraction of positives")
    ax.set_title(f"Calibration — {name}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / f"calibration_{name}.png", dpi=140)
    plt.close(fig)


def _save_feature_importance(
    model: Any, name: str, out_dir: Path, X_train: np.ndarray, y_train: np.ndarray
) -> None:
    import matplotlib.pyplot as plt
    importances: np.ndarray
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
    elif hasattr(model, "coef_"):
        importances = np.abs(model.coef_).ravel()
    else:
        # Permutation importance fallback
        from sklearn.inspection import permutation_importance
        result = permutation_importance(model, X_train, y_train, n_repeats=5, random_state=0)
        importances = result.importances_mean
    order = np.argsort(importances)[::-1][:12]
    names = [FEATURE_NAMES[i] for i in order]
    vals = importances[order]
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.barh(range(len(names))[::-1], vals)
    ax.set_yticks(range(len(names))[::-1])
    ax.set_yticklabels(names)
    ax.set_xlabel("Importance")
    ax.set_title(f"Top features — {name}")
    fig.tight_layout()
    fig.savefig(out_dir / f"feature_importance_{name}.png", dpi=140)
    plt.close(fig)


def train_all(
    X: np.ndarray,
    y: np.ndarray,
    employee_ids: list[str],
    cfg: TrainConfig | None = None,
) -> dict[str, Any]:
    """Train all three baselines and write artefacts. Returns metrics dict."""
    cfg = cfg or TrainConfig()
    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    X_train, y_train, X_val, y_val, X_test, y_test = _split_by_employee(
        X, y, employee_ids, cfg
    )

    models: dict[str, Any] = {
        "logreg": Pipeline([
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(class_weight="balanced", max_iter=2000, random_state=cfg.random_state)),
        ]),
        "rf": RandomForestClassifier(
            n_estimators=300, class_weight="balanced",
            random_state=cfg.random_state, n_jobs=-1,
        ),
        "hgbt": HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.05,
            random_state=cfg.random_state,
        ),
    }

    all_metrics: dict[str, Any] = {
        "config": {
            "n_total": int(len(y)),
            "n_train": int(len(y_train)),
            "n_val": int(len(y_val)),
            "n_test": int(len(y_test)),
            "feature_names": FEATURE_NAMES,
            "test_size": cfg.test_size,
            "val_size": cfg.val_size,
            "random_state": cfg.random_state,
        },
        "models": {},
    }

    for name, model in models.items():
        model.fit(X_train, y_train)
        y_pred_test = model.predict(X_test)
        if hasattr(model, "predict_proba"):
            y_proba_test = model.predict_proba(X_test)[:, 1]
        else:
            y_proba_test = model.decision_function(X_test)

        m_test = _eval(y_test, y_pred_test, y_proba_test)
        m_val = _eval(
            y_val,
            model.predict(X_val),
            model.predict_proba(X_val)[:, 1] if hasattr(model, "predict_proba") else model.decision_function(X_val),
        )

        cm = confusion_matrix(y_test, y_pred_test, labels=[0, 1])
        _save_confusion(cm, name, out_dir)
        _save_calibration(y_test, y_proba_test, name, out_dir)

        # Use the underlying estimator for importance plotting if Pipeline
        underlying = model.named_steps["clf"] if isinstance(model, Pipeline) else model
        X_train_for_imp = (
            model.named_steps["scale"].transform(X_train) if isinstance(model, Pipeline) else X_train
        )
        try:
            _save_feature_importance(underlying, name, out_dir, X_train_for_imp, y_train)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] feature importance failed for {name}: {exc}")

        with open(out_dir / f"model_{name}.pkl", "wb") as fh:
            pickle.dump(model, fh)

        all_metrics["models"][name] = {"val": m_val, "test": m_test}
        print(f"[{name}] test: {m_test}")

    with open(out_dir / "metrics.json", "w", encoding="utf-8") as fh:
        json.dump(all_metrics, fh, indent=2)

    return all_metrics
