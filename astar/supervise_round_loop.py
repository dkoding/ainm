from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from config import DEFAULT_OUTPUT_DIR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Supervise round_loop.py and restart it if it exits or stops heartbeating.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR), help="Artifact root used by the loop.")
    parser.add_argument("--heartbeat-timeout-seconds", type=int, default=600, help="Restart if heartbeat gets older than this.")
    parser.add_argument("--restart-delay-seconds", type=int, default=5, help="Delay before restarting the loop.")
    parser.add_argument("loop_args", nargs=argparse.REMAINDER, help="Arguments passed through to round_loop.py.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    heartbeat_path = Path(args.out_dir) / "loop" / "heartbeat.json"
    loop_args = list(args.loop_args)
    if loop_args and loop_args[0] == "--":
        loop_args = loop_args[1:]
    while True:
        command = [sys.executable, "round_loop.py", *loop_args]
        process = subprocess.Popen(command, cwd=str(Path(__file__).resolve().parent))
        try:
            while True:
                exit_code = process.poll()
                if exit_code is not None:
                    break
                if heartbeat_is_stale(heartbeat_path, timeout_seconds=args.heartbeat_timeout_seconds):
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
                    break
                time.sleep(min(30, max(5, args.restart_delay_seconds)))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        time.sleep(max(1, args.restart_delay_seconds))


def heartbeat_is_stale(path: Path, timeout_seconds: int) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return False
    generated_at = payload.get("generated_at")
    if not generated_at:
        return False
    try:
        timestamp = datetime.fromisoformat(str(generated_at))
    except ValueError:
        return False
    age_seconds = (datetime.now(timezone.utc) - timestamp).total_seconds()
    return age_seconds > float(timeout_seconds)


if __name__ == "__main__":
    main()
