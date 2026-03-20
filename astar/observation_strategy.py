from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class ViewportRequest:
    seed_index: int
    viewport_x: int
    viewport_y: int
    viewport_w: int
    viewport_h: int

    def to_payload(self, round_id: str) -> dict[str, Any]:
        payload = asdict(self)
        payload["round_id"] = round_id
        return payload


def build_round_viewport_plan(
    round_detail: dict[str, Any],
    total_queries: int,
    viewport_size: int = 15,
) -> dict[int, list[ViewportRequest]]:
    if total_queries < 0:
        raise ValueError("total_queries must be non-negative.")
    height = int(round_detail["map_height"])
    width = int(round_detail["map_width"])
    plan: dict[int, list[ViewportRequest]] = {seed_index: [] for seed_index, _ in enumerate(round_detail["initial_states"])}
    if total_queries == 0:
        return plan

    tiled_candidates_by_seed: dict[int, list[tuple[float, ViewportRequest]]] = {}
    repeat_candidates: list[tuple[float, int, ViewportRequest]] = []
    for seed_index, state in enumerate(round_detail["initial_states"]):
        tiled_candidates = build_seed_viewport_candidates(
            state=state,
            seed_index=seed_index,
            map_width=width,
            map_height=height,
            viewport_size=viewport_size,
        )
        tiled_candidates_by_seed[seed_index] = tiled_candidates
        for score, request in tiled_candidates:
            repeat_candidates.append((score, seed_index, request))

    for tile_index in range(max((len(items) for items in tiled_candidates_by_seed.values()), default=0)):
        for seed_index in sorted(plan):
            if sum(len(items) for items in plan.values()) >= total_queries:
                return plan
            if tile_index >= len(tiled_candidates_by_seed[seed_index]):
                continue
            _, request = tiled_candidates_by_seed[seed_index][tile_index]
            plan[seed_index].append(request)

    for _, seed_index, request in sorted(repeat_candidates, key=lambda item: item[0], reverse=True):
        if sum(len(items) for items in plan.values()) >= total_queries:
            break
        plan[seed_index].append(request)

    return plan


def build_seed_viewport_candidates(
    state: dict[str, Any],
    seed_index: int,
    map_width: int,
    map_height: int,
    viewport_size: int = 15,
) -> list[tuple[float, ViewportRequest]]:
    grid = np.asarray(state["grid"], dtype=int)
    settlements = list(state.get("settlements", []))

    requests: list[tuple[float, ViewportRequest]] = []
    for request in build_seed_tiled_sweep_requests(
        seed_index=seed_index,
        map_width=map_width,
        map_height=map_height,
        viewport_size=viewport_size,
    ):
        requests.append((_score_viewport(grid=grid, settlements=settlements, request=request), request))

    return sorted(requests, key=lambda item: item[0], reverse=True)


def build_seed_tiled_sweep_requests(
    seed_index: int,
    map_width: int,
    map_height: int,
    viewport_size: int = 15,
) -> list[ViewportRequest]:
    requests: list[ViewportRequest] = []
    x_segments = _axis_segments(map_width, viewport_size)
    y_segments = _axis_segments(map_height, viewport_size)
    for viewport_y, viewport_h in y_segments:
        for viewport_x, viewport_w in x_segments:
            requests.append(
                ViewportRequest(
                    seed_index=seed_index,
                    viewport_x=viewport_x,
                    viewport_y=viewport_y,
                    viewport_w=viewport_w,
                    viewport_h=viewport_h,
                )
            )
    return requests


def _axis_segments(length: int, viewport_size: int) -> list[tuple[int, int]]:
    if length <= 0:
        return []
    if viewport_size <= 0:
        raise ValueError("viewport_size must be positive.")
    segments: list[tuple[int, int]] = []
    start = 0
    while start < length:
        size = min(viewport_size, length - start)
        segments.append((start, size))
        start += viewport_size
    return segments


def _score_viewport(grid: np.ndarray, settlements: list[dict[str, Any]], request: ViewportRequest) -> float:
    x0 = request.viewport_x
    y0 = request.viewport_y
    x1 = x0 + request.viewport_w
    y1 = y0 + request.viewport_h
    patch = grid[y0:y1, x0:x1]

    settlement_score = 0.0
    for settlement in settlements:
        sx = int(settlement["x"])
        sy = int(settlement["y"])
        if x0 <= sx < x1 and y0 <= sy < y1:
            settlement_score += 6.0
            if settlement.get("has_port"):
                settlement_score += 3.0

    coastline_score = 0.0
    frontier_score = 0.0
    for y in range(patch.shape[0]):
        for x in range(patch.shape[1]):
            gx = x0 + x
            gy = y0 + y
            center = int(grid[gy, gx])
            neighbor_codes = [int(grid[ny, nx]) for nx, ny in _neighbors(gx, gy, grid.shape[1], grid.shape[0])]
            if any((code == 10) != (center == 10) for code in neighbor_codes):
                coastline_score += 0.4
            frontier_score += sum(1 for code in neighbor_codes if code != center) * 0.1

    terrain_diversity = float(len(np.unique(patch))) * 0.5
    return settlement_score + coastline_score + frontier_score + terrain_diversity


def _neighbors(x: int, y: int, width: int, height: int) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx = x + dx
        ny = y + dy
        if 0 <= nx < width and 0 <= ny < height:
            result.append((nx, ny))
    return result
