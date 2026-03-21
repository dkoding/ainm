from __future__ import annotations

from typing import Any, Iterator

import numpy as np

from baseline import terrain_code_to_class_index


FEATURE_COLUMNS = [
    "initial_terrain_code",
    "initial_class_index",
    "is_initial_settlement",
    "initial_has_port",
    "is_land",
    "x_norm",
    "y_norm",
    "nearest_edge_distance_norm",
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
    "radius2_unique_terrain",
    "radius2_ocean_count",
    "radius2_settlement_count",
    "radius2_port_count",
    "radius2_ruin_count",
    "radius2_forest_count",
    "radius2_mountain_count",
    "radius2_coastline_cell_count",
    "local_land_ratio_radius2",
    "coastal_exposure",
    "fjord_complexity",
    "land_component_size_ratio",
    "same_landmass_settlement_count",
    "same_landmass_port_count",
    "nearest_settlement_distance",
    "nearest_port_distance",
    "nearest_ocean_distance",
    "nearest_mountain_distance",
    "seed_settlement_count",
    "seed_port_count",
    "seed_ocean_ratio",
    "seed_forest_ratio",
    "seed_mountain_ratio",
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
    settlement_positions = list(settlements.keys())
    port_positions = [position for position, has_port in settlements.items() if has_port]
    ocean_positions = [(int(x), int(y)) for y, x in np.argwhere(grid == 10)]
    mountain_positions = [(int(x), int(y)) for y, x in np.argwhere(grid == 5)]
    coastal_mask = _build_coastal_mask(grid)
    terrain_edge_map = _terrain_edge_map(grid)
    land_component_labels, land_component_sizes = _build_land_components(grid)
    component_settlement_counts: dict[int, int] = {}
    component_port_counts: dict[int, int] = {}
    for (sx, sy), has_port in settlements.items():
        component_id = int(land_component_labels[sy, sx])
        if component_id < 0:
            continue
        component_settlement_counts[component_id] = component_settlement_counts.get(component_id, 0) + 1
        if has_port:
            component_port_counts[component_id] = component_port_counts.get(component_id, 0) + 1
    grid_size = float(grid.size) if grid.size > 0 else 1.0
    seed_summary = {
        "seed_settlement_count": int(len(settlement_positions)),
        "seed_port_count": int(len(port_positions)),
        "seed_ocean_ratio": float(np.count_nonzero(grid == 10) / grid_size),
        "seed_forest_ratio": float(np.count_nonzero(grid == 4) / grid_size),
        "seed_mountain_ratio": float(np.count_nonzero(grid == 5) / grid_size),
    }

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
                "is_land": int(int(grid[y, x]) != 10),
                "x_norm": float(x / max(width - 1, 1)),
                "y_norm": float(y / max(height - 1, 1)),
                "nearest_edge_distance_norm": float(min(x, y, width - 1 - x, height - 1 - y) / max(width, height, 1)),
                **_local_features(
                    grid,
                    x=x,
                    y=y,
                    radius=neighborhood_radius,
                    coastal_mask=coastal_mask,
                    terrain_edge_map=terrain_edge_map,
                ),
                **_radius2_features(
                    grid,
                    x=x,
                    y=y,
                    coastal_mask=coastal_mask,
                    terrain_edge_map=terrain_edge_map,
                ),
                **_component_features(
                    x=x,
                    y=y,
                    grid=grid,
                    land_component_labels=land_component_labels,
                    land_component_sizes=land_component_sizes,
                    component_settlement_counts=component_settlement_counts,
                    component_port_counts=component_port_counts,
                ),
                "nearest_settlement_distance": float(_nearest_manhattan_distance(x, y, settlement_positions, default=width + height)),
                "nearest_port_distance": float(_nearest_manhattan_distance(x, y, port_positions, default=width + height)),
                "nearest_ocean_distance": float(_nearest_manhattan_distance(x, y, ocean_positions, default=width + height)),
                "nearest_mountain_distance": float(_nearest_manhattan_distance(x, y, mountain_positions, default=width + height)),
                **seed_summary,
            }


def feature_matrix_from_records(records: list[dict[str, Any]], feature_columns: list[str] | None = None) -> np.ndarray:
    selected_columns = feature_columns or FEATURE_COLUMNS
    return np.asarray([[float(record[column]) for column in selected_columns] for record in records], dtype=np.float32)


def _local_features(
    grid: np.ndarray,
    x: int,
    y: int,
    radius: int,
    coastal_mask: np.ndarray,
    terrain_edge_map: np.ndarray,
) -> dict[str, Any]:
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
        "coast_adjacent": int(coastal_mask[y, x]),
        "terrain_edge_count": int(terrain_edge_map[y, x]),
    }


def _radius2_features(
    grid: np.ndarray,
    x: int,
    y: int,
    coastal_mask: np.ndarray,
    terrain_edge_map: np.ndarray,
) -> dict[str, Any]:
    radius = 2
    y0 = max(0, y - radius)
    y1 = min(grid.shape[0], y + radius + 1)
    x0 = max(0, x - radius)
    x1 = min(grid.shape[1], x + radius + 1)
    patch = grid[y0:y1, x0:x1]
    counts = {int(code): int((patch == code).sum()) for code in np.unique(patch)}
    patch_size = float(patch.size) if patch.size > 0 else 1.0
    coastal_patch = coastal_mask[y0:y1, x0:x1]
    terrain_edge_patch = terrain_edge_map[y0:y1, x0:x1]
    coastline_cell_count = int(np.count_nonzero(coastal_patch))
    return {
        "radius2_unique_terrain": int(len(counts)),
        "radius2_ocean_count": counts.get(10, 0),
        "radius2_settlement_count": counts.get(1, 0),
        "radius2_port_count": counts.get(2, 0),
        "radius2_ruin_count": counts.get(3, 0),
        "radius2_forest_count": counts.get(4, 0),
        "radius2_mountain_count": counts.get(5, 0),
        "radius2_coastline_cell_count": coastline_cell_count,
        "local_land_ratio_radius2": float(np.count_nonzero(patch != 10) / patch_size),
        "coastal_exposure": float(coastline_cell_count / patch_size),
        "fjord_complexity": float(np.mean(terrain_edge_patch[coastal_patch])) if np.any(coastal_patch) else 0.0,
    }


def _component_features(
    *,
    x: int,
    y: int,
    grid: np.ndarray,
    land_component_labels: np.ndarray,
    land_component_sizes: dict[int, int],
    component_settlement_counts: dict[int, int],
    component_port_counts: dict[int, int],
) -> dict[str, Any]:
    if int(grid[y, x]) == 10:
        return {
            "land_component_size_ratio": 0.0,
            "same_landmass_settlement_count": 0,
            "same_landmass_port_count": 0,
        }
    component_id = int(land_component_labels[y, x])
    component_size = int(land_component_sizes.get(component_id, 0))
    return {
        "land_component_size_ratio": float(component_size / max(grid.size, 1)),
        "same_landmass_settlement_count": int(component_settlement_counts.get(component_id, 0)),
        "same_landmass_port_count": int(component_port_counts.get(component_id, 0)),
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


def _build_coastal_mask(grid: np.ndarray) -> np.ndarray:
    mask = np.zeros(grid.shape, dtype=bool)
    for y in range(grid.shape[0]):
        for x in range(grid.shape[1]):
            mask[y, x] = _is_coastal(grid, x=x, y=y)
    return mask


def _terrain_edge_map(grid: np.ndarray) -> np.ndarray:
    edge_map = np.zeros(grid.shape, dtype=np.int16)
    for y in range(grid.shape[0]):
        for x in range(grid.shape[1]):
            edge_map[y, x] = _terrain_edge_count(grid, x=x, y=y)
    return edge_map


def _build_land_components(grid: np.ndarray) -> tuple[np.ndarray, dict[int, int]]:
    labels = np.full(grid.shape, -1, dtype=np.int32)
    component_sizes: dict[int, int] = {}
    next_component_id = 0
    for y in range(grid.shape[0]):
        for x in range(grid.shape[1]):
            if int(grid[y, x]) == 10 or labels[y, x] >= 0:
                continue
            stack = [(x, y)]
            labels[y, x] = next_component_id
            size = 0
            while stack:
                cx, cy = stack.pop()
                size += 1
                for nx, ny in _neighbors(cx, cy, grid.shape[1], grid.shape[0]):
                    if int(grid[ny, nx]) == 10 or labels[ny, nx] >= 0:
                        continue
                    labels[ny, nx] = next_component_id
                    stack.append((nx, ny))
            component_sizes[next_component_id] = size
            next_component_id += 1
    return labels, component_sizes


def _neighbors(x: int, y: int, width: int, height: int) -> Iterator[tuple[int, int]]:
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx = x + dx
        ny = y + dy
        if 0 <= nx < width and 0 <= ny < height:
            yield nx, ny


def _nearest_manhattan_distance(x: int, y: int, positions: list[tuple[int, int]], default: int) -> int:
    if not positions:
        return int(default)
    return min(abs(px - x) + abs(py - y) for px, py in positions)
