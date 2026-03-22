from __future__ import annotations

import argparse
import atexit
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from artifacts import ArtifactStore
from astar_client import AstarAPIError, AstarClient
from config import DEFAULT_AINM_BASE_URL, DEFAULT_OUTPUT_DIR, AstarSettings


STATE_PATH = Path("loop") / "loop_state.json"
SCORE_HISTORY_PATH = Path("loop") / "team_round_scores.json"
MISSED_ROUNDS_PATH = Path("loop") / "missed_rounds.json"
EVENT_LOG_PATH = Path("loop") / "events.jsonl"
HEARTBEAT_PATH = Path("loop") / "heartbeat.json"
LOCK_PATH = Path("loop") / "loop.lock"


@dataclass
class LoopState:
    submitted_round_ids: list[str] = field(default_factory=list)
    reviewed_round_ids: list[str] = field(default_factory=list)
    seen_round_ids: list[str] = field(default_factory=list)
    last_active_round_id: str | None = None
    last_tick_at: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "submitted_round_ids": self.submitted_round_ids,
            "reviewed_round_ids": self.reviewed_round_ids,
            "seen_round_ids": self.seen_round_ids,
            "last_active_round_id": self.last_active_round_id,
            "last_tick_at": self.last_tick_at,
        }

    @classmethod
    def from_path(cls, path: Path) -> "LoopState":
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text())
        return cls(
            submitted_round_ids=list(payload.get("submitted_round_ids", [])),
            reviewed_round_ids=list(payload.get("reviewed_round_ids", [])),
            seen_round_ids=list(payload.get("seen_round_ids", [])),
            last_active_round_id=payload.get("last_active_round_id"),
            last_tick_at=payload.get("last_tick_at"),
        )


def parse_args() -> argparse.Namespace:
    secrets = AstarSettings.from_env()
    parser = argparse.ArgumentParser(description="Watch Astar rounds and run the per-round pipeline automatically.")
    parser.add_argument("--token", default=secrets.access_token, help="AINM access_token JWT.")
    parser.add_argument("--base-url", default=DEFAULT_AINM_BASE_URL, help="API base URL.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR), help="Artifact root for loop outputs.")
    parser.add_argument("--poll-seconds", type=int, default=60, help="Default polling interval in seconds.")
    parser.add_argument("--total-queries", type=int, default=50, help="Simulation queries to spend for each new active round.")
    parser.add_argument("--force-lock", action=argparse.BooleanOptionalAction, default=False, help="Replace an existing stale lock file.")
    parser.add_argument(
        "--submit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Submit predictions automatically for each new active round.",
    )
    parser.add_argument(
        "--once",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Process the current state once and exit instead of looping forever.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.token:
        raise SystemExit("--token or AINM_ACCESS_TOKEN is required for round_loop.")

    client = AstarClient(token=args.token, base_url=args.base_url)
    artifact_store = ArtifactStore(root=args.out_dir)
    state_path = Path(args.out_dir) / STATE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(args.out_dir) / LOCK_PATH
    acquire_loop_lock(lock_path=lock_path, force=args.force_lock)
    atexit.register(release_loop_lock, lock_path=lock_path, owner_pid=os.getpid())

    while True:
        state = LoopState.from_path(state_path)
        try:
            tick(args=args, client=client, artifact_store=artifact_store, state=state)
        except Exception as exc:
            print(f"loop warning: {exc}")
            log_loop_event(root=Path(args.out_dir), event_type="tick_error", message=str(exc))
        finally:
            state.last_tick_at = datetime.now(timezone.utc).isoformat()
            state_path.write_text(json.dumps(state.to_payload(), indent=2, sort_keys=True))
            write_heartbeat(root=Path(args.out_dir), state=state)

        if args.once:
            break

        sleep_seconds = compute_sleep_seconds(client=client, default_poll_seconds=args.poll_seconds)
        print(f"loop: sleeping {sleep_seconds}s")
        time.sleep(sleep_seconds)


def tick(args: argparse.Namespace, client: AstarClient, artifact_store: ArtifactStore, state: LoopState) -> None:
    rounds = client.get_rounds()
    my_rounds = client.get_my_rounds()
    leaderboard = client.get_leaderboard()

    artifact_store.write_json(Path("loop") / "rounds_latest.json", rounds)
    artifact_store.write_json(Path("loop") / "my_rounds_latest.json", my_rounds)
    artifact_store.write_json(Path("loop") / "leaderboard_latest.json", leaderboard)
    artifact_store.write_json(SCORE_HISTORY_PATH, build_score_history(my_rounds))
    artifact_store.write_json(MISSED_ROUNDS_PATH, build_missed_rounds_report(my_rounds))
    log_loop_event(root=Path(args.out_dir), event_type="tick", message="loop tick", previous_active_round_id=state.last_active_round_id)

    for round_item in rounds:
        round_id = str(round_item["id"])
        if round_id not in state.seen_round_ids:
            state.seen_round_ids.append(round_id)

    completed_round_ids = [
        str(item["id"])
        for item in rounds
        if str(item.get("status")).lower() == "completed"
    ]
    needs_history_support_refresh = False
    for round_id in completed_round_ids:
        if round_id in state.reviewed_round_ids:
            continue
        if not team_submitted_round(my_rounds, round_id):
            state.reviewed_round_ids.append(round_id)
            continue
        run_post_round_review(args=args, round_id=round_id, out_dir=args.out_dir)
        write_round_score_feedback(root=Path(args.out_dir), round_id=round_id, my_rounds=my_rounds)
        state.reviewed_round_ids.append(round_id)
        needs_history_support_refresh = True
    if needs_history_support_refresh:
        try:
            run_history_support_refresh(args=args, out_dir=args.out_dir)
        except Exception as exc:
            print(f"loop warning: history support refresh failed: {exc}")
            log_loop_event(
                root=Path(args.out_dir),
                event_type="history_support_refresh_error",
                message="history support refresh failed",
                error=str(exc),
            )
        else:
            log_loop_event(
                root=Path(args.out_dir),
                event_type="history_support_refresh",
                message="history support refresh completed",
            )

    active_round = choose_active_round(rounds=rounds, my_rounds=my_rounds)
    if not active_round:
        state.last_active_round_id = None
        print("loop: no active round")
        log_loop_event(root=Path(args.out_dir), event_type="no_active_round", message="no active round")
        return

    active_round_id = str(active_round["id"])
    state.last_active_round_id = active_round_id
    current_predictions = client.get_my_predictions(active_round_id)
    predictions_count = len(current_predictions)
    seeds_count = int(active_round.get("seeds_count", 5) or 5)
    pending_final_overwrite = has_pending_final_overwrite(root=Path(args.out_dir), round_id=active_round_id, seeds_count=seeds_count)

    if predictions_count >= seeds_count:
        if pending_final_overwrite:
            budget = client.get_budget()
            cached_simulations_present = has_cached_simulations(root=Path(args.out_dir), round_id=active_round_id)
            if cached_simulations_present or int(budget["queries_used"]) > 0:
                print(
                    f"loop: round {active_round.get('round_number')} has staged submissions only; resuming final overwrite from cache"
                )
                log_loop_event(
                    root=Path(args.out_dir),
                    event_type="resume_final_overwrite",
                    message="staged submission detected; resuming final overwrite",
                    round_id=active_round_id,
                    round_number=active_round.get("round_number"),
                    predictions_count=predictions_count,
                    seeds_count=seeds_count,
                    queries_used=budget.get("queries_used"),
                    queries_max=budget.get("queries_max"),
                )
                run_resume_round(args=args, round_id=active_round_id, out_dir=args.out_dir)
            else:
                print(f"loop: round {active_round.get('round_number')} has staged submissions only; rerunning final pipeline")
                log_loop_event(
                    root=Path(args.out_dir),
                    event_type="rerun_final_overwrite",
                    message="staged submission detected before simulation; rerunning final pipeline",
                    round_id=active_round_id,
                    round_number=active_round.get("round_number"),
                    predictions_count=predictions_count,
                    seeds_count=seeds_count,
                )
                run_round_pipeline(args=args, round_id=active_round_id, out_dir=args.out_dir)
            if active_round_id not in state.submitted_round_ids:
                state.submitted_round_ids.append(active_round_id)
            return
        print(f"loop: round {active_round.get('round_number')} already has {predictions_count}/{seeds_count} submitted seeds")
        state.submitted_round_ids.append(active_round_id) if active_round_id not in state.submitted_round_ids else None
        log_loop_event(
            root=Path(args.out_dir),
            event_type="already_submitted",
            message="round already fully submitted",
            round_id=active_round_id,
            round_number=active_round.get("round_number"),
            predictions_count=predictions_count,
            seeds_count=seeds_count,
        )
        return

    if 0 < predictions_count < seeds_count:
        print(f"loop: round {active_round.get('round_number')} has partial submission state; resuming")
        log_loop_event(
            root=Path(args.out_dir),
            event_type="resume_round",
            message="partial submission detected",
            round_id=active_round_id,
            round_number=active_round.get("round_number"),
            predictions_count=predictions_count,
            seeds_count=seeds_count,
        )
        run_resume_round(args=args, round_id=active_round_id, out_dir=args.out_dir)
        if active_round_id not in state.submitted_round_ids:
            state.submitted_round_ids.append(active_round_id)
        return

    budget = client.get_budget()
    if int(budget["queries_used"]) >= int(budget["queries_max"]):
        print(f"loop: round {active_round.get('round_number')} has no budget remaining and no submitted predictions")
        log_loop_event(
            root=Path(args.out_dir),
            event_type="budget_exhausted",
            message="no budget remaining",
            round_id=active_round_id,
            round_number=active_round.get("round_number"),
            queries_used=budget.get("queries_used"),
            queries_max=budget.get("queries_max"),
        )
        return

    print(
        "loop: processing active round "
        f"{active_round.get('round_number')} ({active_round_id}) with {args.total_queries} planned queries"
    )
    log_loop_event(
        root=Path(args.out_dir),
        event_type="run_round",
        message="processing active round",
        round_id=active_round_id,
        round_number=active_round.get("round_number"),
        planned_queries=args.total_queries,
    )
    run_round_pipeline(args=args, round_id=active_round_id, out_dir=args.out_dir)
    if args.submit and active_round_id not in state.submitted_round_ids:
        state.submitted_round_ids.append(active_round_id)


def build_score_history(my_rounds: list[dict[str, Any]]) -> dict[str, Any]:
    concise = []
    for item in my_rounds:
        concise.append(
            {
                "round_id": item.get("id") or item.get("round_id"),
                "round_number": item.get("round_number"),
                "status": item.get("status"),
                "started_at": item.get("started_at"),
                "closes_at": item.get("closes_at"),
                "prediction_window_minutes": item.get("prediction_window_minutes"),
                "round_score": item.get("round_score"),
                "seed_scores": item.get("seed_scores"),
                "seeds_submitted": item.get("seeds_submitted"),
                "rank": item.get("rank"),
                "total_teams": item.get("total_teams"),
                "queries_used": item.get("queries_used"),
                "queries_max": item.get("queries_max"),
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rounds": concise,
    }


def build_missed_rounds_report(my_rounds: list[dict[str, Any]]) -> dict[str, Any]:
    missed = []
    for item in my_rounds:
        if str(item.get("status")).lower() != "completed":
            continue
        if int(item.get("seeds_submitted", 0) or 0) > 0:
            continue
        missed.append(
            {
                "round_id": item.get("id") or item.get("round_id"),
                "round_number": item.get("round_number"),
                "started_at": item.get("started_at"),
                "closes_at": item.get("closes_at"),
                "queries_used": item.get("queries_used"),
                "queries_max": item.get("queries_max"),
                "seeds_submitted": item.get("seeds_submitted"),
                "status": item.get("status"),
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "missed_rounds": missed,
    }


def choose_active_round(rounds: list[dict[str, Any]], my_rounds: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates: dict[str, dict[str, Any]] = {}
    for item in rounds:
        if str(item.get("status")).lower() == "active":
            candidates[str(item["id"])] = item
    for item in my_rounds:
        if str(item.get("status")).lower() != "active":
            continue
        round_id = str(item.get("id") or item.get("round_id"))
        candidates.setdefault(round_id, item)
    if not candidates:
        return None
    return max(candidates.values(), key=_round_sort_key)


def team_submitted_round(my_rounds: list[dict[str, Any]], round_id: str) -> bool:
    for item in my_rounds:
        if str(item.get("id") or item.get("round_id")) != round_id:
            continue
        return int(item.get("seeds_submitted", 0) or 0) > 0
    return False


def has_pending_final_overwrite(root: Path, round_id: str, seeds_count: int) -> bool:
    round_root = root / round_id / "team"
    initial_dir = round_root / "submissions_initial"
    final_dir = round_root / "submissions"
    initial_count = len(list(initial_dir.glob("seed_*.json"))) if initial_dir.exists() else 0
    final_count = len(list(final_dir.glob("seed_*.json"))) if final_dir.exists() else 0
    if initial_count < int(seeds_count):
        return False
    if final_count >= int(seeds_count):
        return False
    report_path = root / round_id / "report.json"
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text())
        except json.JSONDecodeError:
            report = {}
        for stage in report.get("submission_stages", []):
            if stage.get("stage") == "final_submit" and stage.get("submitted"):
                return False
    return True


def has_cached_simulations(root: Path, round_id: str) -> bool:
    simulation_root = root / round_id / "team" / "simulations"
    return simulation_root.exists() and any(simulation_root.rglob("query_*.json"))


def run_round_pipeline(args: argparse.Namespace, round_id: str, out_dir: str) -> None:
    command = [
        sys.executable,
        "run_round.py",
        "--round-id",
        round_id,
        "--out-dir",
        out_dir,
        "--simulate",
        "--total-queries",
        str(args.total_queries),
    ]
    if args.submit:
        command.append("--submit")
    else:
        command.append("--no-submit")
    run_local_command(command, cwd=Path(__file__).resolve().parent)


def run_resume_round(args: argparse.Namespace, round_id: str, out_dir: str) -> None:
    command = [
        sys.executable,
        "resume_round.py",
        "--round-id",
        round_id,
        "--out-dir",
        out_dir,
    ]
    if args.submit:
        command.append("--submit")
    else:
        command.append("--no-submit")
    run_local_command(command, cwd=Path(__file__).resolve().parent)


def run_post_round_review(args: argparse.Namespace, round_id: str, out_dir: str) -> None:
    command = [
        sys.executable,
        "post_round_review.py",
        "--round-id",
        round_id,
        "--out-dir",
        out_dir,
    ]
    run_local_command(command, cwd=Path(__file__).resolve().parent)


def run_history_support_refresh(args: argparse.Namespace, out_dir: str) -> None:
    command = [
        sys.executable,
        "refresh_history_support.py",
        "--token",
        args.token,
        "--base-url",
        args.base_url,
        "--out-dir",
        out_dir,
    ]
    run_local_command(command, cwd=Path(__file__).resolve().parent)


def run_local_command(command: list[str], cwd: Path) -> None:
    completed = subprocess.run(command, cwd=str(cwd), check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed with exit code {completed.returncode}: {' '.join(command)}")


def compute_sleep_seconds(client: AstarClient, default_poll_seconds: int) -> int:
    try:
        rounds = client.get_rounds()
    except Exception:
        return max(15, int(default_poll_seconds))

    active_round = next((item for item in rounds if str(item.get("status")).lower() == "active"), None)
    if not active_round:
        return max(30, int(default_poll_seconds))

    closes_at = parse_timestamp(active_round.get("closes_at"))
    if closes_at is None:
        return max(15, int(default_poll_seconds))

    seconds_until_close = int((closes_at - datetime.now(timezone.utc)).total_seconds())
    if seconds_until_close <= 0:
        return 15
    if seconds_until_close <= 180:
        return 15
    if seconds_until_close <= 900:
        return 30
    return max(30, min(int(default_poll_seconds), 120))


def write_round_score_feedback(root: Path, round_id: str, my_rounds: list[dict[str, Any]]) -> Path:
    round_entry = next((item for item in my_rounds if str(item.get("id") or item.get("round_id")) == round_id), None)
    official_score = float(round_entry.get("round_score")) if round_entry and round_entry.get("round_score") is not None else None
    historical_scores = [
        float(item["round_score"])
        for item in my_rounds
        if str(item.get("status")).lower() == "completed"
        and item.get("round_score") is not None
        and str(item.get("id") or item.get("round_id")) != round_id
    ]
    rolling_mean = float(sum(historical_scores) / len(historical_scores)) if historical_scores else None
    report_path = root / round_id / "report.json"
    expected_score = None
    offline_reference_score = None
    offline_reference_kind = None
    selected_variant = None
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text())
        except json.JSONDecodeError:
            report = {}
        selected_variant = report.get("prediction_model")
        strategy_summary = report.get("strategy_evaluation", {}).get("summary", {})
        offline_reference_score = strategy_summary.get("best_variant_mean_round_score")
        evaluation_mode = str(strategy_summary.get("evaluation_mode") or "")
        if offline_reference_score is not None:
            if "fast_rank" in evaluation_mode:
                offline_reference_kind = "ranking_only"
            else:
                expected_score = offline_reference_score
                offline_reference_kind = "holdout_expectation"
    regression_flags = []
    if official_score is not None and expected_score is not None and official_score + 8.0 < float(expected_score):
        regression_flags.append("below_offline_expectation")
    if official_score is not None and rolling_mean is not None and official_score + 8.0 < rolling_mean:
        regression_flags.append("below_recent_official_mean")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "round_id": round_id,
        "selected_variant": selected_variant,
        "official_round_score": official_score,
        "expected_offline_round_score": expected_score,
        "offline_reference_score": offline_reference_score,
        "offline_reference_kind": offline_reference_kind,
        "recent_official_mean_score": rolling_mean,
        "regression_flags": regression_flags,
    }
    output_path = root / round_id / "team" / "score_feedback.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    if regression_flags:
        log_loop_event(
            root=root,
            event_type="score_regression",
            message="official score regressed versus expectations",
            round_id=round_id,
            regression_flags=regression_flags,
            official_round_score=official_score,
            expected_offline_round_score=expected_score,
            recent_official_mean_score=rolling_mean,
        )
    return output_path


def write_heartbeat(root: Path, state: LoopState) -> None:
    heartbeat_path = root / HEARTBEAT_PATH
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                "last_active_round_id": state.last_active_round_id,
                "last_tick_at": state.last_tick_at,
            },
            indent=2,
            sort_keys=True,
        )
    )


def log_loop_event(root: Path, event_type: str, message: str, **fields: Any) -> None:
    event_path = root / EVENT_LOG_PATH
    event_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "event_type": event_type,
        "message": message,
        **fields,
    }
    with event_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def acquire_loop_lock(lock_path: Path, force: bool = False) -> None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            existing = json.loads(lock_path.read_text())
        except json.JSONDecodeError:
            existing = {}
        existing_pid = int(existing.get("pid", 0) or 0)
        if existing_pid and _pid_is_alive(existing_pid) and not force:
            raise SystemExit(f"loop lock already held by pid {existing_pid}: {lock_path}")
    lock_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
    )


def release_loop_lock(lock_path: Path, owner_pid: int) -> None:
    if not lock_path.exists():
        return
    try:
        payload = json.loads(lock_path.read_text())
    except json.JSONDecodeError:
        payload = {}
    if int(payload.get("pid", 0) or 0) == int(owner_pid):
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _round_sort_key(item: dict[str, Any]) -> tuple[datetime, int]:
    started_at = parse_timestamp(item.get("started_at")) or datetime.min.replace(tzinfo=timezone.utc)
    round_number = int(item.get("round_number") or 0)
    return (started_at, round_number)


if __name__ == "__main__":
    main()
