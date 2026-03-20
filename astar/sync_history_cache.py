from __future__ import annotations

import argparse

from artifacts import ArtifactStore
from astar_client import AstarClient
from config import (
    DEFAULT_AINM_BASE_URL,
    DEFAULT_HISTORY_CACHE_PREFIX,
    DEFAULT_OUTPUT_DIR,
    AstarSettings,
)
from history_cache import sync_history_cache


def parse_args() -> argparse.Namespace:
    secrets = AstarSettings.from_env()

    parser = argparse.ArgumentParser(description="Download and cache completed-round Astar history.")
    parser.add_argument("--token", default=secrets.access_token, help="AINM access_token JWT.")
    parser.add_argument("--base-url", default=DEFAULT_AINM_BASE_URL, help="API base URL.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR), help="Where to write cached history.")
    parser.add_argument(
        "--analysis",
        action=argparse.BooleanOptionalAction,
        default=bool(secrets.access_token),
        help="Fetch per-seed /analysis payloads for completed rounds. Requires authentication.",
    )
    parser.add_argument(
        "--round-limit",
        type=int,
        help="Optional limit on how many completed rounds to refresh, newest first.",
    )
    parser.add_argument(
        "--cache-prefix",
        default=DEFAULT_HISTORY_CACHE_PREFIX,
        help="Relative cache directory inside --out-dir.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.analysis and not args.token:
        raise SystemExit("--analysis requires --token or AINM_ACCESS_TOKEN.")

    client = AstarClient(token=args.token, base_url=args.base_url)
    artifact_store = ArtifactStore(root=args.out_dir)
    summary = sync_history_cache(
        client=client,
        artifact_store=artifact_store,
        cache_prefix=args.cache_prefix,
        round_limit=args.round_limit,
        sync_analysis=args.analysis,
    )
    print(
        "history cache: "
        f"{summary['completed_rounds_cached']} completed rounds, "
        f"{summary['analysis_cached_seeds']} cached analysis seeds, "
        f"written under {args.out_dir}/{args.cache_prefix}"
    )


if __name__ == "__main__":
    main()
