from __future__ import annotations

from typing import Any

import numpy as np

from validation import validate_prediction_array


def entropy_weighted_kl(
    ground_truth: Any,
    prediction: Any,
    clip_min: float = 1e-12,
) -> float:
    p = validate_prediction_array(ground_truth)
    q = np.asarray(prediction, dtype=float)
    if q.shape != p.shape:
        raise ValueError(f"prediction shape {q.shape} does not match ground_truth shape {p.shape}.")
    q = np.clip(q, clip_min, 1.0)
    q = q / q.sum(axis=-1, keepdims=True)

    positive = p > 0
    kl_terms = np.zeros_like(p)
    kl_terms[positive] = p[positive] * (np.log(p[positive]) - np.log(q[positive]))
    kl = np.sum(kl_terms, axis=-1)

    entropy_terms = np.zeros_like(p)
    entropy_terms[positive] = p[positive] * np.log(p[positive])
    entropy = -np.sum(entropy_terms, axis=-1)

    entropy_sum = float(entropy.sum())
    if entropy_sum <= 0:
        return 0.0
    return float((entropy * kl).sum() / entropy_sum)


def seed_score(ground_truth: Any, prediction: Any, clip_min: float = 1e-12) -> float:
    weighted_kl = entropy_weighted_kl(ground_truth=ground_truth, prediction=prediction, clip_min=clip_min)
    return float(max(0.0, min(100.0, 100.0 * np.exp(-3.0 * weighted_kl))))


def round_score(seed_scores: list[float]) -> float:
    if not seed_scores:
        return 0.0
    return float(sum(seed_scores) / len(seed_scores))
