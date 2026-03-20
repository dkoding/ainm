from __future__ import annotations

from typing import Any, Iterator

import numpy as np

from baseline import terrain_code_to_class_index


FEATURE_COLUMNS = [
    "initial_terrain_code",
    "initial_class_index",
    "is_initial_settlement",
    "initial_has_port",
    "neighbor_count",
    "neighbor_unique_terrain",
    "neighbor_ocean_count",
    "neighbor_plains_count",
    "neighbor_settlement_count",
    "neighbor_port_count",
    "neighbor_ruin_count",
    "neighbor_forest_count",
    "neighbor_mountain_count",
    "coast_adjacent",
    "terrain_edge_count",
]


def iter_state_feature_records(
    state: dict[str, Any],
    seed_index: int,
    round_id: str = "",
    round_number: int = 0,
    neighborhood_radius: int = 1,
) -> Iterator[dict[str, Any]]:
    grid = np.asarray(state["grid"], dtype=int)
    settlements = {(int(item["x"]), int(item["y"])): bool(item.get("has_port")) for item in state.get("settlements", [])}

    height, width = grid.shape
    for y in range(height):
        for x in range(width):
            yield {
                "round_id": round_id,
                "round_number": int(round_number),
                "seed_index": int(seed_index),
                "x": x,
                "y": y,
                "initial_terrain_code": int(grid[y, x]),
                "initial_class_index": int(terrain_code_to_class_index(int(grid[y, x]))),
                "is_initial_settlement": int((x, y) in settlements),
                "initial_has_port": int(settlements.get((x, y), False)),
                **_local_features(grid, x=x, y=y, radius=neighborhood_radius),
            }


def feature_matrix_from_records(records: list[dict[str, Any]], feature_columns: list[str] | None = None) -> np.ndarray:
    selected_columns = feature_columns or FEATURE_COLUMNS
    return np.asarray([[float(record[column]) for column in selected_columns] for record in records], dtype=np.float32)


def _local_features(grid: np.ndarray, x: int, y: int, radius: int) -> dict[str, Any]:
    y0 = max(0, y - radius)
    y1 = min(grid.shape[0], y + radius + 1)
    x0 = max(0, x - radius)
    x1 = min(grid.shape[1], x + radius + 1)
    patch = grid[y0:y1, x0:x1]
    counts = {int(code): int((patch == code).sum()) for code in np.unique(patch)}
    return {
        "neighbor_count": int(patch.size),
        "neighbor_unique_terrain": int(len(counts)),
        "neighbor_ocean_count": counts.get(10, 0),
        "neighbor_plains_count": counts.get(11, 0) + counts.get(0, 0),
        "neighbor_settlement_count": counts.get(1, 0),
        "neighbor_port_count": counts.get(2, 0),
        "neighbor_ruin_count": counts.get(3, 0),
        "neighbor_forest_count": counts.get(4, 0),
        "neighbor_mountain_count": counts.get(5, 0),
        "coast_adjacent": int(_is_coastal(grid, x=x, y=y)),
        "terrain_edge_count": int(_terrain_edge_count(grid, x=x, y=y)),
    }


def _is_coastal(grid: np.ndarray, x: int, y: int) -> bool:
    here_is_water = int(grid[y, x]) == 10
    for nx, ny in _neighbors(x=x, y=y, width=grid.shape[1], height=grid.shape[0]):
        other_is_water = int(grid[ny, nx]) == 10
        if here_is_water != other_is_water:
            return True
    return False


def _terrain_edge_count(grid: np.ndarray, x: int, y: int) -> int:
    center = int(grid[y, x])
    return sum(1 for nx, ny in _neighbors(x=x, y=y, width=grid.shape[1], height=grid.shape[0]) if int(grid[ny, nx]) != center)


def _neighbors(x: int, y: int, width: int, height: int) -> Iterator[tuple[int, int]]:
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx = x + dx
        ny = y + dy
        if 0 <= nx < width and 0 <= ny < height:
            yield nx, ny
