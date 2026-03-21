from __future__ import annotations

from typing import Any

import numpy as np

from validation import validate_prediction_array


def cell_entropy_grid(ground_truth: Any) -> np.ndarray:
    p = validate_prediction_array(ground_truth)
    positive = p > 0
    entropy_terms = np.zeros_like(p)
    entropy_terms[positive] = p[positive] * np.log(p[positive])
    return -np.sum(entropy_terms, axis=-1)


def entropy_weighted_kl(
    ground_truth: Any,
    prediction: Any,
    clip_min: float = 1e-12,
    cell_mask: Any | None = None,
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

    entropy = cell_entropy_grid(p)

    if cell_mask is not None:
        mask = np.asarray(cell_mask, dtype=bool)
        if mask.shape != entropy.shape:
            raise ValueError(f"cell_mask shape {mask.shape} does not match cell grid shape {entropy.shape}.")
        kl = np.where(mask, kl, 0.0)
        entropy = np.where(mask, entropy, 0.0)

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


def score_breakdown(
    ground_truth: Any,
    prediction: Any,
    clip_min: float = 1e-12,
    dynamic_entropy_threshold: float = 0.05,
) -> dict[str, float]:
    entropy = cell_entropy_grid(ground_truth)
    dynamic_mask = entropy >= float(dynamic_entropy_threshold)
    weighted_kl = entropy_weighted_kl(ground_truth=ground_truth, prediction=prediction, clip_min=clip_min)
    dynamic_weighted_kl = entropy_weighted_kl(
        ground_truth=ground_truth,
        prediction=prediction,
        clip_min=clip_min,
        cell_mask=dynamic_mask,
    )
    dynamic_entropy_mass = float(entropy[dynamic_mask].sum())
    total_entropy_mass = float(entropy.sum())
    return {
        "weighted_kl": float(weighted_kl),
        "score": float(max(0.0, min(100.0, 100.0 * np.exp(-3.0 * weighted_kl)))),
        "dynamic_weighted_kl": float(dynamic_weighted_kl),
        "dynamic_score": float(max(0.0, min(100.0, 100.0 * np.exp(-3.0 * dynamic_weighted_kl)))),
        "dynamic_cell_fraction": float(dynamic_mask.mean()) if dynamic_mask.size else 0.0,
        "dynamic_entropy_mass_fraction": float(dynamic_entropy_mass / total_entropy_mass) if total_entropy_mass > 0 else 0.0,
        "mean_cell_entropy": float(entropy.mean()) if entropy.size else 0.0,
        "max_cell_entropy": float(entropy.max()) if entropy.size else 0.0,
    }
