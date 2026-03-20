from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


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
    queries_per_seed: int,
    viewport_size: int = 15,
) -> dict[int, list[ViewportRequest]]:
    height = int(round_detail["map_height"])
    width = int(round_detail["map_width"])
    plan: dict[int, list[ViewportRequest]] = {}
    for seed_index, state in enumerate(round_detail["initial_states"]):
        plan[seed_index] = build_seed_viewport_plan(
            state=state,
            seed_index=seed_index,
            map_width=width,
            map_height=height,
            query_count=queries_per_seed,
            viewport_size=viewport_size,
        )
    return plan


def build_seed_viewport_plan(
    state: dict[str, Any],
    seed_index: int,
    map_width: int,
    map_height: int,
    query_count: int,
    viewport_size: int = 15,
) -> list[ViewportRequest]:
    if query_count <= 0:
        return []

    settlements = list(state.get("settlements", []))
    radius = max(1, viewport_size // 2)
    candidate_points: list[tuple[int, int]] = []

    if settlements:
        scored_settlements = sorted(
            settlements,
            key=lambda item: (
                int(bool(item.get("has_port"))),
                _local_density_score(item, settlements, radius),
            ),
            reverse=True,
        )
        candidate_points.extend((int(item["x"]), int(item["y"])) for item in scored_settlements)

    candidate_points.extend(
        [
            (map_width // 2, map_height // 2),
            (map_width // 4, map_height // 4),
            (3 * map_width // 4, map_height // 4),
            (map_width // 4, 3 * map_height // 4),
            (3 * map_width // 4, 3 * map_height // 4),
        ]
    )

    requests: list[ViewportRequest] = []
    seen_windows: set[tuple[int, int, int, int]] = set()
    for center_x, center_y in candidate_points:
        viewport_x, viewport_y = _clamp_viewport(center_x, center_y, viewport_size, map_width, map_height)
        window = (viewport_x, viewport_y, viewport_size, viewport_size)
        if window in seen_windows:
            continue
        seen_windows.add(window)
        requests.append(
            ViewportRequest(
                seed_index=seed_index,
                viewport_x=viewport_x,
                viewport_y=viewport_y,
                viewport_w=viewport_size,
                viewport_h=viewport_size,
            )
        )
        if len(requests) >= query_count:
            break

    return requests


def _local_density_score(target: dict[str, Any], settlements: list[dict[str, Any]], radius: int) -> int:
    target_x = int(target["x"])
    target_y = int(target["y"])
    score = 0
    for other in settlements:
        if other is target:
            continue
        if abs(int(other["x"]) - target_x) <= radius and abs(int(other["y"]) - target_y) <= radius:
            score += 1
    return score


def _clamp_viewport(center_x: int, center_y: int, viewport_size: int, map_width: int, map_height: int) -> tuple[int, int]:
    half = viewport_size // 2
    viewport_x = min(max(center_x - half, 0), max(map_width - viewport_size, 0))
    viewport_y = min(max(center_y - half, 0), max(map_height - viewport_size, 0))
    return viewport_x, viewport_y
