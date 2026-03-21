from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watch a crop-classifier training run and print live status lines.")
    parser.add_argument("run_dir", type=Path, help="Training output directory to watch.")
    parser.add_argument("--pid", type=int, help="Optional training process PID.")
    parser.add_argument("--interval", type=float, default=20.0, help="Polling interval in seconds.")
    parser.add_argument("--jsonl", type=Path, help="Optional JSONL path for structured watcher output.")
    parser.add_argument("--once", action="store_true", help="Print one snapshot and exit.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    if not run_dir.exists():
        raise SystemExit(f"Missing run directory: {run_dir}")

    watcher = TrainingWatcher(run_dir=run_dir, pid=args.pid)
    while True:
        snapshot = watcher.collect_snapshot()
        print(format_snapshot(snapshot), flush=True)
        if args.jsonl:
            append_jsonl(args.jsonl.resolve(), snapshot)
        if args.once:
            break
        time.sleep(max(1.0, args.interval))


class TrainingWatcher:
    def __init__(self, run_dir: Path, pid: int | None):
        self.run_dir = run_dir
        self.pid = pid or self.load_pid_from_metadata()
        self.history_path = run_dir / "history.json"
        self.status_path = run_dir / "status.json"
        self.checkpoint_path = run_dir / "last_crop_classifier.pt"
        self.best_path = run_dir / "best_crop_classifier.pt"
        self._cached_checkpoint_mtime: float | None = None
        self._cached_history_from_checkpoint: list[dict] = []

    def collect_snapshot(self) -> dict:
        if self.pid is None:
            self.pid = self.load_pid_from_metadata()
        snapshot = {
            "timestamp": utc_now_iso(),
            "run_dir": str(self.run_dir),
            "pid": self.pid,
            "process_alive": is_process_alive(self.pid),
            "gpu": read_gpu_snapshot(),
            "files": {
                "last_checkpoint_mtime": path_mtime(self.checkpoint_path),
                "best_checkpoint_mtime": path_mtime(self.best_path),
            },
        }
        status = self.read_status()
        if status is not None:
            snapshot.update(
                {
                    "stage": status.get("stage"),
                    "epoch_count": status.get("epoch_count"),
                    "current": status.get("current"),
                    "best": status.get("best"),
                    "best_epoch": status.get("best_epoch"),
                    "best_top1": status.get("best_top1"),
                    "epochs_without_improvement": status.get("epochs_without_improvement"),
                }
            )
            return snapshot

        history = self.read_history()
        if history:
            best_row = max(history, key=lambda row: row["val_top1"])
            snapshot.update(
                {
                    "stage": "running" if snapshot["process_alive"] else "unknown",
                    "epoch_count": len(history),
                    "current": history[-1],
                    "best": best_row,
                    "best_epoch": best_row["epoch"],
                    "best_top1": best_row["val_top1"],
                    "epochs_without_improvement": epochs_without_improvement(history, best_row["epoch"]),
                }
            )
        else:
            snapshot.update(
                {
                    "stage": "starting" if snapshot["process_alive"] else "unknown",
                    "epoch_count": 0,
                    "current": None,
                    "best": None,
                    "best_epoch": None,
                    "best_top1": None,
                    "epochs_without_improvement": None,
                }
            )
        return snapshot

    def load_pid_from_metadata(self) -> int | None:
        metadata_path = self.run_dir / "run_metadata.json"
        if not metadata_path.exists():
            return None
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        value = payload.get("pid")
        return int(value) if isinstance(value, int) else None

    def read_status(self) -> dict | None:
        if not self.status_path.exists():
            return None
        try:
            return json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def read_history(self) -> list[dict]:
        if self.history_path.exists():
            try:
                payload = json.loads(self.history_path.read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    return payload
            except (OSError, json.JSONDecodeError):
                pass
        return self.read_history_from_checkpoint()

    def read_history_from_checkpoint(self) -> list[dict]:
        if not self.checkpoint_path.exists():
            return self._cached_history_from_checkpoint
        checkpoint_mtime = self.checkpoint_path.stat().st_mtime
        if self._cached_checkpoint_mtime == checkpoint_mtime:
            return self._cached_history_from_checkpoint
        try:
            import torch

            payload = torch.load(self.checkpoint_path, map_location="cpu")
        except Exception:
            return self._cached_history_from_checkpoint
        history = payload.get("history", [])
        if isinstance(history, list):
            self._cached_checkpoint_mtime = checkpoint_mtime
            self._cached_history_from_checkpoint = history
        return self._cached_history_from_checkpoint


def epochs_without_improvement(history: list[dict], best_epoch: int) -> int:
    return max(0, len(history) - int(best_epoch))


def is_process_alive(pid: int | None) -> bool | None:
    if pid is None:
        return None
    command = ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError:
        return None
    output = completed.stdout.strip()
    if not output or output.startswith("INFO:"):
        return False
    return str(pid) in output


def read_gpu_snapshot() -> dict | None:
    command = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,memory.total,power.draw",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        return None
    row = next(csv.reader([lines[0]]), None)
    if not row or len(row) < 4:
        return None
    return {
        "utilization_gpu": safe_float(row[0]),
        "memory_used_mb": safe_float(row[1]),
        "memory_total_mb": safe_float(row[2]),
        "power_draw_w": safe_float(row[3]),
    }


def format_snapshot(snapshot: dict) -> str:
    current = snapshot.get("current") or {}
    best = snapshot.get("best") or {}
    gpu = snapshot.get("gpu") or {}
    parts = [
        f"[{snapshot['timestamp']}]",
        f"stage={snapshot.get('stage')}",
        f"epoch={current.get('epoch', '?')}",
        f"best_val_top1={format_metric(best.get('val_top1'))}@{best.get('epoch', '?')}",
        f"stale={snapshot.get('epochs_without_improvement', '?')}",
        f"process_alive={snapshot.get('process_alive')}",
    ]
    if current:
        parts.append(f"train_top1={format_metric(current.get('train_top1'))}")
        parts.append(f"val_top1={format_metric(current.get('val_top1'))}")
        parts.append(f"val_loss={format_metric(current.get('val_loss'))}")
    if gpu:
        parts.append(f"gpu={int(gpu['utilization_gpu'])}%")
        parts.append(f"mem={int(gpu['memory_used_mb'])}/{int(gpu['memory_total_mb'])}MB")
        parts.append(f"power={gpu['power_draw_w']:.1f}W")
    return " ".join(parts)


def format_metric(value) -> str:
    if value is None:
        return "?"
    return f"{float(value):.6f}"


def safe_float(value: str) -> float | None:
    value = value.strip()
    if not value or value == "[N/A]":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def path_mtime(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.write("\n")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()
