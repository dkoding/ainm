from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from artifacts import ArtifactStore
from astar_client import AstarAPIError, AstarClient
from config import DEFAULT_HISTORY_CACHE_PREFIX


def sync_history_cache(
    client: AstarClient,
    artifact_store: ArtifactStore,
    cache_prefix: str = DEFAULT_HISTORY_CACHE_PREFIX,
    sync_analysis: bool = True,
) -> dict[str, Any]:
    cache_root = Path(cache_prefix)
    public_rounds = client.get_rounds()
    completed_rounds = sorted(
        (round_item for round_item in public_rounds if round_item.get("status") == "completed"),
        key=_round_sort_key,
        reverse=True,
    )

    artifact_store.write_json(cache_root / "public" / "rounds.json", public_rounds)

    summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cache_prefix": str(cache_root),
        "completed_rounds_cached": 0,
        "analysis_cached_seeds": 0,
        "analysis_enabled": bool(sync_analysis and client.is_authenticated),
        "public_rounds_total": len(public_rounds),
        "rounds": [],
    }

    if client.is_authenticated:
        try:
            team_rounds = client.get_my_rounds()
        except AstarAPIError as exc:
            summary["my_rounds_error"] = str(exc)
        else:
            artifact_store.write_json(cache_root / "team" / "my_rounds.json", team_rounds)

    for round_item in completed_rounds:
        round_id = str(round_item["id"])
        round_entry: dict[str, Any] = {
            "round_id": round_id,
            "round_number": round_item.get("round_number"),
            "event_date": round_item.get("event_date"),
            "status": round_item.get("status"),
            "analysis_cached_seeds": [],
            "analysis_errors": [],
        }
        try:
            round_detail = client.get_round_detail(round_id)
        except AstarAPIError as exc:
            round_entry["round_detail_error"] = str(exc)
            summary["rounds"].append(round_entry)
            continue

        seeds_count = int(round_detail.get("seeds_count", 0))
        round_entry["seeds_count"] = seeds_count
        artifact_store.write_json(cache_root / "rounds" / round_id / "public" / "round_detail.json", round_detail)

        if sync_analysis and client.is_authenticated:
            for seed_index in range(seeds_count):
                try:
                    analysis = client.get_analysis(round_id, seed_index)
                except AstarAPIError as exc:
                    round_entry["analysis_errors"].append(
                        {
                            "seed_index": seed_index,
                            "status_code": exc.status_code,
                            "message": str(exc),
                        }
                    )
                    continue
                artifact_store.write_json(
                    cache_root / "rounds" / round_id / "team" / "analysis" / f"seed_{seed_index}.json",
                    analysis,
                )
                round_entry["analysis_cached_seeds"].append(seed_index)
                summary["analysis_cached_seeds"] += 1

        summary["completed_rounds_cached"] += 1
        summary["rounds"].append(round_entry)

    artifact_store.write_json(cache_root / "index.json", summary)
    return summary


def load_history_index(root: str | Path, cache_prefix: str = DEFAULT_HISTORY_CACHE_PREFIX) -> dict[str, Any] | None:
    index_path = Path(root) / cache_prefix / "index.json"
    if not index_path.exists():
        return None
    return json.loads(index_path.read_text())


def summarize_history_cache(root: str | Path, cache_prefix: str = DEFAULT_HISTORY_CACHE_PREFIX) -> dict[str, Any] | None:
    index = load_history_index(root=root, cache_prefix=cache_prefix)
    if not index:
        return None
    round_entries = index.get("rounds", [])
    return {
        "cache_path": str(Path(root) / cache_prefix),
        "generated_at": index.get("generated_at"),
        "completed_rounds_cached": int(index.get("completed_rounds_cached", len(round_entries))),
        "analysis_cached_seeds": int(
            index.get(
                "analysis_cached_seeds",
                sum(len(entry.get("analysis_cached_seeds", [])) for entry in round_entries),
            )
        ),
        "analysis_enabled": bool(index.get("analysis_enabled")),
    }


def iter_cached_analysis_records(
    root: str | Path,
    cache_prefix: str = DEFAULT_HISTORY_CACHE_PREFIX,
) -> Iterator[dict[str, Any]]:
    index = load_history_index(root=root, cache_prefix=cache_prefix)
    if not index:
        return

    cache_root = Path(root) / cache_prefix / "rounds"
    for round_entry in index.get("rounds", []):
        round_id = str(round_entry["round_id"])
        for seed_index in round_entry.get("analysis_cached_seeds", []):
            analysis_path = cache_root / round_id / "team" / "analysis" / f"seed_{seed_index}.json"
            if not analysis_path.exists():
                continue
            yield {
                "round_id": round_id,
                "seed_index": int(seed_index),
                "path": str(analysis_path),
                "analysis": json.loads(analysis_path.read_text()),
            }


def _round_sort_key(round_item: dict[str, Any]) -> tuple[str, int]:
    return (
        str(round_item.get("event_date", "")),
        int(round_item.get("round_number", 0) or 0),
    )
