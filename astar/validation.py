from __future__ import annotations

from typing import Any

import numpy as np


CLASS_COUNT = 6


class AstarValidationError(ValueError):
    pass


def validate_round_id(round_id: Any) -> str:
    if not isinstance(round_id, str) or not round_id.strip():
        raise AstarValidationError("round_id must be a non-empty string.")
    return round_id


def validate_rounds_response(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise AstarValidationError("/rounds response must be a list.")
    validated: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise AstarValidationError("Each /rounds item must be an object.")
        validate_round_id(item.get("id"))
        if "status" not in item:
            raise AstarValidationError("/rounds items must include status.")
        validated.append(item)
    return validated


def validate_round_detail_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AstarValidationError("/rounds/{round_id} response must be an object.")
    width = int(payload["map_width"])
    height = int(payload["map_height"])
    seeds_count = int(payload["seeds_count"])
    states = payload["initial_states"]
    if not isinstance(states, list) or len(states) != seeds_count:
        raise AstarValidationError("initial_states length must equal seeds_count.")
    for state in states:
        validate_initial_state(state, expected_width=width, expected_height=height)
    return payload


def validate_initial_state(state: Any, expected_width: int, expected_height: int) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise AstarValidationError("initial state must be an object.")
    grid = np.asarray(state["grid"], dtype=int)
    if grid.shape != (expected_height, expected_width):
        raise AstarValidationError(
            f"initial state grid shape {grid.shape} does not match expected {(expected_height, expected_width)}."
        )
    settlements = state.get("settlements", [])
    if not isinstance(settlements, list):
        raise AstarValidationError("initial state settlements must be a list.")
    for settlement in settlements:
        _validate_coordinate_pair(
            x=settlement.get("x"),
            y=settlement.get("y"),
            width=expected_width,
            height=expected_height,
            label="initial settlement",
        )
    return state


def validate_budget_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AstarValidationError("/budget response must be an object.")
    validate_round_id(payload.get("round_id"))
    queries_used = int(payload["queries_used"])
    queries_max = int(payload["queries_max"])
    if queries_used < 0 or queries_max < 0 or queries_used > queries_max:
        raise AstarValidationError("budget response has inconsistent query counts.")
    if not isinstance(payload.get("active"), bool):
        raise AstarValidationError("budget response must include boolean active.")
    return payload


def validate_simulate_request(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AstarValidationError("simulate payload must be an object.")
    validate_round_id(payload.get("round_id"))
    seed_index = int(payload["seed_index"])
    if not 0 <= seed_index <= 4:
        raise AstarValidationError("seed_index must be in [0, 4].")
    width = int(payload["viewport_w"])
    height = int(payload["viewport_h"])
    if not 5 <= width <= 15 or not 5 <= height <= 15:
        raise AstarValidationError("viewport_w and viewport_h must be in [5, 15].")
    int(payload["viewport_x"])
    int(payload["viewport_y"])
    return payload


def validate_simulate_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AstarValidationError("/simulate response must be an object.")
    viewport = payload["viewport"]
    if not isinstance(viewport, dict):
        raise AstarValidationError("/simulate response viewport must be an object.")
    width = int(viewport["w"])
    height = int(viewport["h"])
    grid = np.asarray(payload["grid"], dtype=int)
    if grid.shape != (height, width):
        raise AstarValidationError(f"/simulate grid shape {grid.shape} does not match viewport {(height, width)}.")
    settlements = payload.get("settlements", [])
    if not isinstance(settlements, list):
        raise AstarValidationError("/simulate settlements must be a list.")
    for settlement in settlements:
        _validate_coordinate_pair(
            x=settlement.get("x"),
            y=settlement.get("y"),
            width=int(payload["width"]),
            height=int(payload["height"]),
            label="simulated settlement",
        )
    validate_budget_response(
        {
            "round_id": payload.get("round_id") or "unknown-round",
            "queries_used": payload["queries_used"],
            "queries_max": payload["queries_max"],
            "active": True,
        }
    )
    return payload


def validate_analysis_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AstarValidationError("/analysis response must be an object.")
    width = int(payload["width"])
    height = int(payload["height"])
    initial_grid = np.asarray(payload["initial_grid"], dtype=int)
    if initial_grid.shape != (height, width):
        raise AstarValidationError("/analysis initial_grid shape does not match width/height.")
    ground_truth = np.asarray(payload["ground_truth"], dtype=float)
    if ground_truth.shape != (height, width, CLASS_COUNT):
        raise AstarValidationError(f"/analysis ground_truth shape {ground_truth.shape} is invalid.")
    prediction = payload.get("prediction")
    if prediction is not None:
        tensor = np.asarray(prediction, dtype=float)
        if tensor.shape != (height, width, CLASS_COUNT):
            raise AstarValidationError(f"/analysis prediction shape {tensor.shape} is invalid.")
    return payload


def validate_prediction_array(
    prediction: Any,
    expected_height: int | None = None,
    expected_width: int | None = None,
) -> np.ndarray:
    tensor = np.asarray(prediction, dtype=float)
    if tensor.ndim != 3 or tensor.shape[-1] != CLASS_COUNT:
        raise AstarValidationError(f"prediction must have shape HxWx{CLASS_COUNT}; got {tensor.shape}.")
    if expected_height is not None and tensor.shape[0] != expected_height:
        raise AstarValidationError(f"prediction height {tensor.shape[0]} does not match expected {expected_height}.")
    if expected_width is not None and tensor.shape[1] != expected_width:
        raise AstarValidationError(f"prediction width {tensor.shape[1]} does not match expected {expected_width}.")
    if not np.isfinite(tensor).all():
        raise AstarValidationError("prediction contains non-finite values.")
    if np.any(tensor < 0):
        raise AstarValidationError("prediction contains negative probabilities.")
    sums = tensor.sum(axis=-1)
    if not np.allclose(sums, 1.0, atol=1e-6):
        raise AstarValidationError("prediction probabilities must sum to 1.0 per cell.")
    return tensor


def validate_submission_payload(
    payload: Any,
    expected_round_id: str | None = None,
    expected_height: int | None = None,
    expected_width: int | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AstarValidationError("submit payload must be an object.")
    round_id = validate_round_id(payload.get("round_id"))
    if expected_round_id is not None and round_id != expected_round_id:
        raise AstarValidationError(f"submit payload round_id {round_id} does not match expected {expected_round_id}.")
    seed_index = int(payload["seed_index"])
    if not 0 <= seed_index <= 4:
        raise AstarValidationError("submit payload seed_index must be in [0, 4].")
    tensor = validate_prediction_array(payload["prediction"], expected_height=expected_height, expected_width=expected_width)
    if np.any(tensor <= 0):
        raise AstarValidationError("submit payload prediction must be strictly positive in every class for every cell.")
    return payload


def validate_my_predictions_response(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise AstarValidationError("/my-predictions response must be a list.")
    for item in payload:
        if not isinstance(item, dict):
            raise AstarValidationError("/my-predictions items must be objects.")
        int(item["seed_index"])
    return payload


def validate_my_rounds_response(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise AstarValidationError("/my-rounds response must be a list.")
    for item in payload:
        if not isinstance(item, dict):
            raise AstarValidationError("/my-rounds items must be objects.")
        validate_round_id(item.get("round_id") or item.get("id"))
    return payload


def _validate_coordinate_pair(x: Any, y: Any, width: int, height: int, label: str) -> None:
    xi = int(x)
    yi = int(y)
    if not 0 <= xi < width or not 0 <= yi < height:
        raise AstarValidationError(f"{label} coordinate ({xi}, {yi}) is outside the map bounds {width}x{height}.")
